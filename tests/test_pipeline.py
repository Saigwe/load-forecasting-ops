"""Unit tests for the loaders' tricky parts, and checks on a finished fixture run (FORECAST_DB)."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ingestion"), str(ROOT / "forecasting")]
import sources  # noqa: E402
from live import periods_for  # noqa: E402

DB = os.environ.get("FORECAST_DB", str(ROOT / "warehouse" / "fixture.duckdb"))
STATE = Path(os.environ.get("FORECAST_STATE", ROOT / "data" / "fixture" / "ops-log"))


def test_neso_date_formats_parse_without_day_month_swaps():
    parsed = sources.parse_settlement_date(pd.Series(["01-JAN-2021", "10-Jan-23", "2026-01-10", '"2025-03-04"']))
    assert list(parsed) == [dt.date(2021, 1, 1), dt.date(2023, 1, 10), dt.date(2026, 1, 10), dt.date(2025, 3, 4)]


def test_upsert_is_idempotent():
    con = duckdb.connect()
    df = pd.DataFrame({"k": [1, 2], "v": [10, 20]})
    for _ in range(3):
        sources.upsert(con, "t", df, ["k"])
    sources.upsert(con, "t", pd.DataFrame({"k": [2], "v": [99]}), ["k"])
    assert con.execute("select k, v from bronze.t order by k").fetchall() == [(1, 10), (2, 99)]


@pytest.mark.parametrize("day,periods", [(dt.date(2025, 3, 30), 46), (dt.date(2025, 7, 1), 48), (dt.date(2025, 10, 26), 50)])
def test_settlement_periods_for_clock_change_days(day, periods):
    assert len(periods_for(day)) == periods


def test_fixture_run_scored_every_method_and_issued_forecasts_before_the_day():
    con = duckdb.connect(DB, read_only=True)
    methods = {m for (m,) in con.execute("select distinct method from gold.fct_forecast_errors").fetchall()}
    assert {"lgbm_day_ahead", "lgbm_neso_residual", "neso_day_ahead", "naive_last_week"} <= methods
    late = con.execute("select count(*) from bronze.model_forecasts where issued_at >= cast(target_date as timestamp)").fetchone()[0]
    assert late == 0


def test_daily_run_left_a_report_and_a_green_log():
    runs = [json.loads(l) for l in (STATE / "run_log.jsonl").read_text().splitlines()]
    assert runs[-1]["ok"]
    report = json.loads(sorted((STATE / "reports").glob("report_*.json"))[-1].read_text())
    assert report["status"] in ("GREEN", "AMBER") and report["tomorrow"]


def test_state_export_merges_with_an_existing_log(tmp_path):
    """The second daily run merges into a log written by the first: same rows, no duplicates, no type errors."""
    import shutil
    import subprocess

    db = tmp_path / "copy.duckdb"
    shutil.copy(DB, db)
    cmd = [sys.executable, str(ROOT / "ops" / "state.py"), "export", "--db", str(db), "--state", str(tmp_path / "s")]
    for _ in range(3):
        subprocess.run(cmd, check=True, capture_output=True)
    log = pd.read_csv(tmp_path / "s" / "live_forecasts.csv")
    assert len(log) > 0 and not log.duplicated(["model", "target_date", "settlement_period"]).any()
