"""Synthetic bronze tables with the real schemas, so CI runs dbt, the backtest, the live forecast and the morning
report without the network. Two years of half-hourly demand (with the 46- and 50-period clock-change days), a
'NESO' forecast published at 09:45 the day before, hourly weather (actual and forecast) and bank holidays.

Usage: python tests/fixtures/make_fixture.py --db warehouse/fixture.duckdb
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pandas as pd

UK = ZoneInfo("Europe/London")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="warehouse/fixture.duckdb")
    args = ap.parse_args()
    rng = np.random.default_rng(19)
    start, end = dt.date(2023, 1, 1), dt.date(2024, 12, 31)
    hours = pd.date_range("2023-01-01", "2025-01-03 23:00", freq="h")
    doy = hours.day_of_year.to_numpy()
    temp = 10 - 7 * np.cos(2 * np.pi * (doy - 20) / 365) + 4 * np.sin(2 * np.pi * (hours.hour.to_numpy() - 9) / 24) \
        + rng.normal(0, 2, len(hours))
    solar = np.clip(500 * np.sin(np.pi * (hours.hour.to_numpy() - 6) / 13), 0, None) * (1 - 0.5 * np.cos(2 * np.pi * (doy - 172) / 365)) / 1.5
    wind = rng.gamma(3, 5, len(hours))
    actual = pd.DataFrame({"ts": hours, "temp_c": temp, "solar_wm2": solar, "wind_kmh": wind})
    forecast = actual.assign(temp_c=actual.temp_c + rng.normal(0, 1, len(hours)),
                             solar_wm2=(actual.solar_wm2 * rng.uniform(0.8, 1.2, len(hours))).clip(0),
                             wind_kmh=actual.wind_kmh * rng.uniform(0.8, 1.2, len(hours)))
    forecast = forecast[forecast.ts >= "2024-03-06"]
    temp_at = actual.set_index("ts").temp_c
    solar_at = actual.set_index("ts").solar_wm2

    rows, day = [], start
    holidays = {dt.date(2023, 12, 25), dt.date(2023, 12, 26), dt.date(2024, 1, 1), dt.date(2024, 12, 25), dt.date(2024, 12, 26)}
    while day <= end:
        t0 = dt.datetime.combine(day, dt.time(), UK).astimezone(dt.timezone.utc)
        t1 = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), UK).astimezone(dt.timezone.utc)
        n = int((t1 - t0).total_seconds() // 1800)
        for p in range(1, n + 1):
            ts = (t0 + dt.timedelta(minutes=30 * (p - 1))).replace(tzinfo=None)
            local_h = (p - 1) / 2
            shape = 0.75 + 0.2 * np.exp(-((local_h - 18) ** 2) / 6) + 0.12 * np.exp(-((local_h - 8.5) ** 2) / 3)
            weekend = 0.9 if day.weekday() >= 5 or day in holidays else 1.0
            h = pd.Timestamp(ts).floor("h")
            nd = 30000 * shape * weekend + 450 * max(0, 15.5 - temp_at[h]) - 9 * solar_at[h] + rng.normal(0, 400)
            rows.append((day, p, round(nd), round(nd * 1.1), round(nd * 0.9), 500, round(9 * solar_at[h])))
        day += dt.timedelta(days=1)
    demand = pd.DataFrame(rows, columns=["settlement_date", "settlement_period", "nd", "tsd", "england_wales_demand",
                                         "embedded_wind_generation", "embedded_solar_generation"])
    demand["forecast_actual_indicator"] = "A"
    neso = demand[demand.settlement_date >= dt.date(2023, 4, 1)][["settlement_date", "settlement_period", "nd"]].copy()
    neso = pd.DataFrame({"target_date": neso.settlement_date, "settlement_period": neso.settlement_period,
                         "neso_forecast_mw": (neso.nd * rng.normal(1, 0.025, len(neso))).round(),
                         "neso_outturn_mw": neso.nd,
                         "published_at": pd.to_datetime(neso.settlement_date) - pd.Timedelta(hours=14, minutes=15)})
    hol = pd.DataFrame({"holiday_date": sorted(holidays), "region": "england-and-wales", "title": "Bank holiday"})

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(args.db)
    con.execute("create schema if not exists bronze")
    for name, df in [("demand", demand), ("neso_forecast", neso), ("weather_actual", actual[actual.ts < "2024-12-28"]),
                     ("weather_forecast", forecast), ("bank_holidays", hol)]:
        con.execute(f"create or replace table bronze.{name} as select * from df")
    con.execute("""create or replace table bronze.model_forecasts (model varchar, target_date date, settlement_period integer,
                   forecast_mw double, issued_at timestamp, run_id varchar)""")
    print(f"fixture: {len(demand):,} half hours, {len(neso):,} NESO forecasts -> {args.db}")


if __name__ == "__main__":
    main()
