"""Walk-forward backtest of the LightGBM day-ahead forecasts. Two models:
  lgbm_day_ahead     forecasts demand from lags, calendar and weather forecasts
  lgbm_neso_residual starts from NESO's published day-ahead forecast (public at 09:45) and learns its systematic
                     error from the same features: forecast = NESO + predicted error

For each month from --start: train on every day that would have been known by then (target dates at least two
days before the month starts), then forecast each day of the month as at 09:45 the day before. Each forecast row is
stamped issued_at = target date - 1 day, 09:45 (UK local time), so dbt's leakage test can check it. Results go to
bronze.model_forecasts and dbt scores them against NESO and the naive baseline.

Usage: python forecasting/backtest.py --db warehouse/load.duckdb --start 2024-04-01
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import duckdb
import lightgbm as lgb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import FEATURES, RESIDUAL_FEATURES, add_features, frame  # noqa: E402

MODELS = {"lgbm_day_ahead": FEATURES, "lgbm_neso_residual": RESIDUAL_FEATURES}
PARAMS = {"objective": "l1", "learning_rate": 0.05, "num_leaves": 63, "min_data_in_leaf": 50, "feature_fraction": 0.9,
          "bagging_fraction": 0.9, "bagging_freq": 1, "seed": 0, "verbose": -1, "deterministic": True,
          "force_row_wise": True}
ROUNDS = 800


def fit(train: pd.DataFrame, model: str) -> lgb.Booster:
    train = train.dropna(subset=["nd_mw", "nd_lag7", "nd_lag14", "d1_morning_mw"])
    if model == "lgbm_neso_residual":
        train = train.dropna(subset=["neso_forecast_mw"])
        return lgb.train(PARAMS, lgb.Dataset(train[RESIDUAL_FEATURES], train.nd_mw - train.neso_forecast_mw),
                         num_boost_round=ROUNDS)
    return lgb.train(PARAMS, lgb.Dataset(train[FEATURES], train.nd_mw), num_boost_round=ROUNDS)


def predict(booster: lgb.Booster, rows: pd.DataFrame, model: str):
    if model == "lgbm_neso_residual":
        return rows.neso_forecast_mw + booster.predict(rows[RESIDUAL_FEATURES])
    return booster.predict(rows[FEATURES])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="warehouse/load.duckdb")
    ap.add_argument("--start", default="2024-04-01")
    ap.add_argument("--summary", type=Path, default=Path("results/backtest_summary.json"))
    args = ap.parse_args()
    con = duckdb.connect(args.db)
    d = add_features(frame(con, recent_outturn=True))  # outturn up to this morning, not just the lagging file
    last = d.settlement_date.max()
    months = pd.date_range(args.start, last, freq="MS")
    preds, t0, run_id, summary = [], time.time(), f"backtest-{pd.Timestamp.now():%Y%m%d%H%M}", {}
    for model, features in MODELS.items():
        for m in months:
            cutoff = m - pd.Timedelta(days=2)
            booster = fit(d[d.settlement_date < cutoff], model)
            test = d[(d.settlement_date >= m) & (d.settlement_date < m + pd.offsets.MonthBegin(1))].dropna(subset=["nd_lag7"])
            if model == "lgbm_neso_residual":
                test = test.dropna(subset=["neso_forecast_mw"])
            if test.empty:
                continue
            preds.append(pd.DataFrame({
                "model": model, "target_date": test.settlement_date.dt.date, "settlement_period": test.settlement_period,
                "forecast_mw": predict(booster, test, model).round(0),
                "issued_at": test.settlement_date - pd.Timedelta(days=1) + pd.Timedelta(hours=9, minutes=45),
                "run_id": run_id}))
        importance = pd.Series(booster.feature_importance("gain"), index=features).sort_values(ascending=False)
        summary[model] = {"top_features": (importance / importance.sum()).round(3).head(8).to_dict()}
    out = pd.concat(preds, ignore_index=True)
    con.execute("delete from bronze.model_forecasts where run_id like 'backtest-%'")
    con.execute("insert into bronze.model_forecasts by name select * from out")
    summary.update({"months": len(months), "forecasts": len(out), "seconds": round(time.time() - t0, 1)})
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
