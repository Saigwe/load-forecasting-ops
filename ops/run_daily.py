"""The daily run, step by step, with retries and a run log. Scheduled by .github/workflows/daily.yml at 10:15 UTC
(after NESO publishes its day-ahead forecast at 09:45 UK time).

  1. load       incremental loads (demand, NESO forecasts, weather, holidays); --backfill on a fresh runner
  2. state-in   restore the forecast log: backtest forecasts (results/) and live forecasts (ops-log branch)
  3. dbt        build and test
  4. forecast   tomorrow's forecasts (forecasting/live.py)
  5. dbt        rebuild with the new forecasts (the leakage test checks they were issued before the day)
  6. report     the morning report (Slack when SLACK_WEBHOOK_URL is set)
  7. state-out  save live forecasts and the run log for the next run

Any step failing after its retries stops the run with a non-zero exit code: the workflow goes red and GitHub emails.
Usage: python ops/run_daily.py --db warehouse/load.duckdb --state ops-log [--backfill] [--offline]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def step(name: str, cmd: list[str], log: list, retries: int = 2, cwd: Path = ROOT, env: dict | None = None) -> None:
    import os

    for attempt in range(retries + 1):
        t = time.time()
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env={**os.environ, **(env or {})})
        log.append({"step": name, "attempt": attempt + 1, "ok": r.returncode == 0, "seconds": round(time.time() - t, 1),
                    "tail": (r.stdout + r.stderr).strip().splitlines()[-3:]})
        print(f"[{name}] attempt {attempt + 1}: {'ok' if r.returncode == 0 else 'FAILED'} ({log[-1]['seconds']}s)", flush=True)
        if r.returncode == 0:
            return
        print((r.stdout + r.stderr)[-2000:], flush=True)
        time.sleep(30 * (attempt + 1))
    raise SystemExit(f"step {name} failed after {retries + 1} attempts")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="warehouse/load.duckdb")
    ap.add_argument("--state", default="ops-log", help="folder holding the ops-log branch checkout")
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--offline", action="store_true", help="CI fixture: no network loads, no Elexon call")
    ap.add_argument("--target", help="forecast target day (default: tomorrow)")
    args = ap.parse_args()
    py, db = sys.executable, str(Path(args.db).resolve())
    dbt = str(Path(sys.executable).with_name("dbt"))
    log: list = []
    started = dt.datetime.now(dt.timezone.utc)
    try:
        if not args.offline:
            step("load", [py, "ingestion/load.py", "backfill" if args.backfill else "incremental", "--db", db], log)
        step("state-in", [py, "ops/state.py", "import", "--db", db, "--state", args.state]
             + (["--no-backtest-file"] if args.offline else []), log, retries=0)
        step("dbt", [dbt, "build", "--profiles-dir", ".", "--quiet"], log, cwd=ROOT / "dbt", env={"DUCKDB_PATH": db}, retries=0)
        as_of = (["--as-of", f"{dt.date.fromisoformat(args.target) - dt.timedelta(days=1)}T10:15:00"]
                 if args.target and args.offline else [])
        step("forecast", [py, "forecasting/live.py", "--db", db] + (["--offline"] if args.offline else [])
             + (["--target", args.target] if args.target else []) + as_of, log)
        step("dbt-after-forecast", [dbt, "build", "--profiles-dir", ".", "--quiet"], log, cwd=ROOT / "dbt",
             env={"DUCKDB_PATH": db}, retries=0)
        report_day = (dt.date.fromisoformat(args.target) - dt.timedelta(days=1)).isoformat() if args.target else None
        step("report", [py, "ops/morning_report.py", "--db", db, "--out", str(Path(args.state) / "reports")]
             + (["--today", report_day] if report_day else []), log, retries=0)
        step("state-out", [py, "ops/state.py", "export", "--db", db, "--state", args.state], log, retries=0)
        ok = True
    except SystemExit:
        ok = False
    Path(args.state).mkdir(parents=True, exist_ok=True)
    with open(Path(args.state) / "run_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"started_at": started.isoformat(), "ok": ok, "steps": log}) + "\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
