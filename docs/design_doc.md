# Design doc: Load Forecasting Ops (GB day-ahead demand)

| | |
|---|---|
| **Author** | Stanley Igwe |
| **Status** | Core build complete; daily DAG scheduled on GitHub Actions |
| **Last updated** | 2026-10-26 |

## 1. Problem and users
- **Users:** control-room and trading teams who plan tomorrow's balancing and positions; operations managers who need the morning picture.
- **Questions they need answered:** What will demand be tomorrow, half-hour by half-hour and at the peak? How good have our forecasts been lately? Did anything break overnight?
- **Current pain (scenario):** an analyst downloads data, reruns a spreadsheet model and emails a chart. When they're away, no report goes out, and nobody knows how accurate the forecasts have been.

## 2. Requirements
| Type | Requirement |
|---|---|
| Functional | Daily day-ahead forecast before 11:00 UK; morning report with yesterday's accuracy and tomorrow's peak. |
| Correctness | No leakage: every forecast stamped with its issue time and tested; clock-change days handled. |
| Freshness / SLA | Runs at 10:15 UTC; AMBER status if any input is stale; a failed run alerts by email. |
| Scale | 90k half-hours of history; the full backtest of two models takes about 4 minutes on a laptop. |
| Cost | Free: public APIs and GitHub Actions minutes. |

## 3. Design
- **Layers:** bronze (raw API data, upserted by natural key) → silver (typed demand on the UTC clock, weather actual and forecast) → gold (half-hour facts, forecast errors by method, accuracy daily and monthly).
- **Key choices:**
  - The forecast information set is NESO's own at 09:45, so the comparison is fair.
  - Live forecasts and backtests share one code path (`features.py`), so they can't drift apart.
  - State (the forecast log) lives on a separate branch, so `main` stays code-only.

## 4. Options considered
| Decision | Options | Chosen | Why |
|---|---|---|---|
| Benchmark | Naive only; NESO's published forecast | Both | Beating naive is easy; NESO is the bar a real team must clear. |
| Model | Forecast demand; forecast NESO's error | Both, keep the residual | The residual model wins 23 of 31 months; the standalone one shows what's possible without NESO. |
| Weather in training | Actuals; forecasts | Forecasts where they exist, actuals before | Archived forecasts start in March 2024; training on actuals before that is standard and disclosed. |
| Orchestration | Airflow; cron on a server; GitHub Actions schedule | GitHub Actions | One daily job doesn't need a scheduler cluster; retries, alerts and logs come built in. |
| State between runs | Cache; artifacts; a branch | Branch (`ops-log`) | Durable, visible, and diffable; artifacts expire, caches get evicted. |

## 5. Risks and what I'd change at 10x scale
- The live residual model depends on Elexon publishing NESO's half-hourly forecast in time; if it's missing, the standalone model still runs and the report shows which ran.
- MAPE hides peak error, which matters most operationally; add peak-time and peak-level accuracy, and quantile forecasts.
- At 10x (regional forecasts): move to Airflow or Dagster with per-region partitions, a feature store, and model monitoring for drift.
