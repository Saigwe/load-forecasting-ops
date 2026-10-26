"""Tomorrow's day-ahead forecast, run each morning after NESO publishes its own (09:45 UK).

  1. NESO's latest half-hourly day-ahead forecast for tomorrow, from Elexon's open BMRS API (the NESO open-data
     portal only has 11 cardinal points live; its half-hourly history appears after the fact)
  2. both models refitted on everything known now (outturn to this morning, from NESO's fresh feed)
  3. 46, 48 or 50 settlement periods for tomorrow, placed on the UTC clock, with the day-ahead weather forecast
Rows go to bronze.model_forecasts with run_id live-<date> and issued_at = now (UK local), so dbt scores them once
the outturn arrives and its leakage test checks they were issued before the day.

Usage: python forecasting/live.py --db warehouse/load.duckdb [--target 2026-10-27]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest import MODELS, fit, predict  # noqa: E402
from features import add_features, frame  # noqa: E402

UK = ZoneInfo("Europe/London")
ELEXON = "https://data.elexon.co.uk/bmrs/api/v1/forecast/demand/day-ahead/latest"


def periods_for(day: dt.date) -> pd.DataFrame:
    """Settlement periods for a UK day: half hours from local midnight to the next, so 46, 48 or 50."""
    start = dt.datetime.combine(day, dt.time(), UK).astimezone(dt.timezone.utc)
    end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), UK).astimezone(dt.timezone.utc)
    n = int((end - start).total_seconds() // 1800)
    return pd.DataFrame({"settlement_period": range(1, n + 1),
                         "period_start_utc": [start.replace(tzinfo=None) + dt.timedelta(minutes=30 * i) for i in range(n)]})


def neso_forecast_for(day: dt.date) -> tuple[pd.DataFrame, str | None]:
    url = f"{ELEXON}?from={day.isoformat()}T00:00Z&to={(day + dt.timedelta(days=1)).isoformat()}T00:00Z&format=json"
    req = urllib.request.Request(url, headers={"User-Agent": "load-forecasting-ops/1.0"})
    rows = json.loads(urllib.request.urlopen(req, timeout=120).read()).get("data", [])
    rows = [r for r in rows if r["settlementDate"] == day.isoformat() and r.get("boundary") == "N"]
    df = pd.DataFrame({"settlement_period": [r["settlementPeriod"] for r in rows],
                       "neso_forecast_mw": [r["nationalDemand"] for r in rows]})
    return df, max((r["publishTime"] for r in rows), default=None)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="warehouse/load.duckdb")
    ap.add_argument("--target", help="target day (default: tomorrow, UK time)")
    ap.add_argument("--offline", action="store_true", help="skip the Elexon call (CI fixture): standalone model only")
    ap.add_argument("--as-of", help="replays: the time the forecast is made (UK local), default now")
    args = ap.parse_args()
    now = dt.datetime.now(UK)
    target = dt.date.fromisoformat(args.target) if args.target else now.date() + dt.timedelta(days=1)
    con = duckdb.connect(args.db)

    history = frame(con, recent_outturn=True)
    rows = periods_for(target)
    weather = con.execute("select ts, temp_c as temp_forecast_c, solar_wm2 as solar_forecast_wm2, wind_kmh as wind_forecast_kmh "
                          "from bronze.weather_forecast").df()
    rows = rows.assign(hour=rows.period_start_utc.dt.floor("h")).merge(weather.rename(columns={"ts": "hour"}), on="hour", how="left")
    holidays = set(con.execute("select holiday_date from bronze.bank_holidays where region = 'england-and-wales'").df().holiday_date)
    neso, neso_published = (pd.DataFrame(columns=["settlement_period", "neso_forecast_mw"]), None) if args.offline else neso_forecast_for(target)
    rows = rows.merge(neso, on="settlement_period", how="left").assign(
        settlement_date=pd.Timestamp(target), nd_mw=float("nan"), is_bank_holiday=target in holidays)
    features = add_features(pd.concat([history, rows.drop(columns=["hour", "period_start_utc"])], ignore_index=True))
    target_rows = features[features.settlement_date == pd.Timestamp(target)]

    # issued_at is the real clock time; a replay of a past day states its as-of time instead (the day before, 10:15)
    issued = dt.datetime.fromisoformat(args.as_of) if args.as_of else now.replace(tzinfo=None, microsecond=0)
    if issued >= dt.datetime.combine(target, dt.time()):
        raise SystemExit(f"refusing to issue a day-ahead forecast for {target} at {issued}: the day has started")
    out, report = [], {"target_date": str(target), "issued_at": str(issued), "periods": len(target_rows),
                       "neso_published_at": neso_published}
    for model in MODELS:
        if model == "lgbm_neso_residual" and target_rows.neso_forecast_mw.isna().any():
            report[model] = "skipped: NESO's half-hourly forecast for the target day is not available"
            continue
        booster = fit(features[features.settlement_date < pd.Timestamp(target) - pd.Timedelta(days=1)], model)
        fc = np.asarray(predict(booster, target_rows, model), dtype=float).round(0)
        out.append(pd.DataFrame({"model": model, "target_date": target, "settlement_period": target_rows.settlement_period,
                                 "forecast_mw": fc, "issued_at": issued, "run_id": f"live-{target}"}))
        report[model] = {"peak_mw": float(fc.max()), "peak_period": int(target_rows.settlement_period.iloc[int(fc.argmax())]),
                         "energy_gwh": round(float(fc.sum()) * 0.5 / 1000, 1)}
    if not target_rows.neso_forecast_mw.isna().all():
        report["neso_day_ahead"] = {"peak_mw": float(target_rows.neso_forecast_mw.max())}
    if out:
        live = pd.concat(out, ignore_index=True)
        con.execute("delete from bronze.model_forecasts where run_id = ?", [f"live-{target}"])
        con.execute("insert into bronze.model_forecasts by name select * from live")
        con.execute("create table if not exists bronze.neso_live_forecast (target_date date, settlement_period integer, "
                    "neso_forecast_mw double, published_at varchar)")
        con.execute("delete from bronze.neso_live_forecast where target_date = ?", [target])
        if neso_published:
            snap = neso.assign(target_date=target, published_at=neso_published)
            con.execute("insert into bronze.neso_live_forecast by name select * from snap")
    print(json.dumps(report, default=str))


if __name__ == "__main__":
    main()
