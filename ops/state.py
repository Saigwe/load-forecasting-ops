"""Carry the forecast log between runs on a fresh CI runner.

  import  backtest forecasts from results/backtest_forecasts.parquet (committed with the code) and live forecasts
          from <state>/live_forecasts.csv (the ops-log branch) into bronze.model_forecasts
  export  live forecasts back to <state>/live_forecasts.csv, de-duplicated (a rerun replaces a day, never doubles it)

Usage: python ops/state.py import|export --db warehouse/load.duckdb --state ops-log
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BACKTEST = ROOT / "results" / "backtest_forecasts.parquet"
KEY = ["model", "target_date", "settlement_period"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["import", "export", "save-backtest"])
    ap.add_argument("--db", default="warehouse/load.duckdb")
    ap.add_argument("--state", type=Path, default=Path("ops-log"))
    ap.add_argument("--no-backtest-file", action="store_true", help="don't import the committed real-data backtest (fixture runs)")
    args = ap.parse_args()
    con = duckdb.connect(args.db)
    con.execute("""create table if not exists bronze.model_forecasts (model varchar, target_date date,
        settlement_period integer, forecast_mw double, issued_at timestamp, run_id varchar)""")
    live_csv = args.state / "live_forecasts.csv"
    if args.action == "save-backtest":
        df = con.execute("select * from bronze.model_forecasts where run_id like 'backtest-%'").df()
        df.to_parquet(BACKTEST, index=False)
        print(f"saved {len(df):,} backtest forecasts to {BACKTEST}")
    elif args.action == "import":
        frames = []
        if BACKTEST.exists() and not args.no_backtest_file:
            frames.append(pd.read_parquet(BACKTEST))
        if live_csv.exists():
            frames.append(pd.read_csv(live_csv, parse_dates=["issued_at"]))
        if frames:
            df = pd.concat(frames, ignore_index=True)
            df["target_date"] = pd.to_datetime(df.target_date).dt.date
            con.execute("delete from bronze.model_forecasts where run_id in (select distinct run_id from df)")
            con.execute("insert into bronze.model_forecasts by name select * from df")
        print(f"imported {sum(len(f) for f in frames):,} forecasts")
    else:
        df = con.execute("select * from bronze.model_forecasts where run_id like 'live-%'").df()
        if live_csv.exists():
            df = pd.concat([pd.read_csv(live_csv), df], ignore_index=True)
        # one type per column before merging: the CSV gives text, DuckDB gives dates and timestamps
        df["target_date"] = pd.to_datetime(df.target_date).dt.strftime("%Y-%m-%d")
        df["issued_at"] = pd.to_datetime(df.issued_at)
        df = df.sort_values("issued_at").drop_duplicates(KEY, keep="last").sort_values(KEY)
        args.state.mkdir(parents=True, exist_ok=True)
        df.to_csv(live_csv, index=False)
        print(f"exported {len(df):,} live forecasts to {live_csv}")


if __name__ == "__main__":
    main()
