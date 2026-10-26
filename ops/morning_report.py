"""The morning ops report: is the data fresh, how did yesterday's forecasts do, what does tomorrow look like.

Status is GREEN when every input is fresh and tomorrow's forecasts exist; AMBER when an input is stale or yesterday's
error was unusually high; RED when tomorrow has no forecast. Writes Markdown and JSON, and posts to Slack when
SLACK_WEBHOOK_URL is set (nothing is sent otherwise).

Usage: python ops/morning_report.py --db warehouse/load.duckdb --out results/ops
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

UK = ZoneInfo("Europe/London")
LABEL = {"lgbm_neso_residual": "Model (NESO + learned error)", "lgbm_day_ahead": "Model (standalone)",
         "neso_day_ahead": "NESO day-ahead", "naive_last_week": "Naive (same day last week)"}


def period_time(p: int) -> str:
    m = (p - 1) * 30
    return f"{m // 60:02d}:{m % 60:02d}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="warehouse/load.duckdb")
    ap.add_argument("--out", type=Path, default=Path("results/ops"))
    ap.add_argument("--today", help="report date (default: today, UK time)")
    args = ap.parse_args()
    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(UK).date()
    yesterday, tomorrow = today - dt.timedelta(days=1), today + dt.timedelta(days=1)
    con = duckdb.connect(args.db, read_only=True)
    q = lambda sql, *p: con.execute(sql, list(p)).fetchall()

    fresh = {
        "NESO outturn (forecast-performance feed)": q("select max(target_date) from bronze.neso_forecast where neso_outturn_mw is not null")[0][0],
        "NESO historic demand file": q("select max(settlement_date) from bronze.demand")[0][0],
        "weather forecast": q("select cast(max(ts) as date) from bronze.weather_forecast")[0][0],
    }
    stale = {k: v for k, v in fresh.items()
             if v is None or (k.startswith("NESO outturn") and v < yesterday) or (k == "weather forecast" and v < tomorrow)}
    scored = q("""select method, avg(ape), count(*), max(abs(error_mw)) from gold.fct_forecast_errors
                  where settlement_date = ? group by 1 order by 2""", yesterday)
    rolling = dict(q("""select method, mape_30d from gold.rpt_forecast_accuracy_daily
                        where settlement_date = (select max(settlement_date) from gold.rpt_forecast_accuracy_daily
                                                 where settlement_date <= ?)""", yesterday))
    usual = dict(q("""select method, quantile_cont(mape, 0.9) from gold.rpt_forecast_accuracy_daily
                      where settlement_date between ? and ? group by 1""", yesterday - dt.timedelta(days=90), yesterday - dt.timedelta(days=1)))
    tomorrow_fc = q("""select model, max(forecast_mw), arg_max(settlement_period, forecast_mw), sum(forecast_mw) * 0.5 / 1000,
                              max(issued_at), count(*)
                       from bronze.model_forecasts where target_date = ? and run_id like 'live-%' group by 1""", tomorrow)
    neso_tomorrow = q("select max(neso_forecast_mw), arg_max(settlement_period, neso_forecast_mw) from bronze.neso_live_forecast "
                      "where target_date = ?", tomorrow) if q("select count(*) from information_schema.tables where table_name = 'neso_live_forecast'")[0][0] else []

    unusual = [m for m, ape, _, _ in scored if m in usual and usual[m] and ape > usual[m]]
    status = "RED" if not tomorrow_fc else ("AMBER" if stale or unusual else "GREEN")
    lines = [f"*Load forecast ops: {today:%a %d %b %Y}*  status *{status}*", ""]
    if scored:
        lines += [f"*Yesterday ({yesterday:%d %b}), MAPE by method* (30-day rolling in brackets)"]
        lines += [f"• {LABEL.get(m, m)}: {ape:.2%} ({rolling.get(m, float('nan')):.2%}), worst half hour {worst:,.0f} MW"
                  for m, ape, _, worst in scored]
    else:
        lines += [f"_No outturn for {yesterday:%d %b} yet: scoring waits for NESO's feed._"]
    lines += ["", f"*Tomorrow ({tomorrow:%a %d %b}): forecast peak*"]
    for model, peak, period, energy, issued, n in sorted(tomorrow_fc, key=lambda r: r[0], reverse=True):
        lines.append(f"• {LABEL.get(model, model)}: {peak:,.0f} MW at {period_time(period)}, {energy:,.0f} GWh over {n} periods")
    if neso_tomorrow and neso_tomorrow[0][0]:
        lines.append(f"• NESO day-ahead: {neso_tomorrow[0][0]:,.0f} MW at {period_time(neso_tomorrow[0][1])}")
    if not tomorrow_fc:
        lines.append("• *No forecast for tomorrow*: check the run log.")
    lines += ["", "*Data freshness*"] + [f"• {k}: {v}{'  ⚠ stale' if k in stale else ''}" for k, v in fresh.items()]
    if unusual:
        lines.append(f"⚠ Yesterday's error was above its usual 90th percentile for: {', '.join(LABEL.get(m, m) for m in unusual)}")
    text = "\n".join(lines)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"report_{today}.md").write_text(text.replace("*", "**") + "\n", encoding="utf-8")
    summary = {"date": str(today), "status": status, "stale": {k: str(v) for k, v in stale.items()},
               "yesterday": {m: {"mape": a, "half_hours": n} for m, a, n, _ in scored},
               "tomorrow": {m: {"peak_mw": p, "peak_period": per, "energy_gwh": e} for m, p, per, e, _, _ in tomorrow_fc},
               "rolling_mape_30d": rolling}
    (args.out / f"report_{today}.json").write_text(json.dumps(summary, indent=1, default=str))
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if webhook:
        req = urllib.request.Request(webhook, data=json.dumps({"text": text}).encode(), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30)
    print(text)
    print(f"\n(posted to Slack: {'yes' if webhook else 'no, SLACK_WEBHOOK_URL not set'})")


if __name__ == "__main__":
    main()
