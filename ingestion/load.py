"""Load everything: `backfill` (five years from the CSVs and archives) or `incremental` (the daily run: only what's
new since each table's watermark). Both are idempotent. A load report goes to stdout as JSON.

Usage
    python ingestion/load.py backfill --db warehouse/load.duckdb --start 2021-10-01
    python ingestion/load.py incremental --db warehouse/load.duckdb
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sources  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["backfill", "incremental"])
    ap.add_argument("--db", default="warehouse/load.duckdb")
    ap.add_argument("--raw", type=Path, default=Path("data/raw"))
    ap.add_argument("--start", default="2021-10-01")
    args = ap.parse_args()
    start = dt.date.fromisoformat(args.start)
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(args.db)
    t0, report = time.time(), {"mode": args.mode}
    if args.mode == "backfill":
        report["demand_rows"] = sources.demand_backfill(con, args.raw, start)
    else:
        report["demand_rows"], report["demand_watermark"] = sources.demand_incremental(con)
    report["neso_forecast_rows"] = sources.neso_forecasts(con)
    report["weather_actual_rows"], report["weather_forecast_rows"] = sources.weather(con, start)
    report["holiday_rows"] = sources.holidays(con)
    con.execute("""create table if not exists bronze.model_forecasts (model varchar, target_date date,
        settlement_period integer, forecast_mw double, issued_at timestamp, run_id varchar)""")
    report["demand_through"] = str(con.execute("select max(settlement_date) from bronze.demand").fetchone()[0])
    report["seconds"] = round(time.time() - t0, 1)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
