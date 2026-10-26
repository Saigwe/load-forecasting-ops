PY ?= python
DB ?= warehouse/load.duckdb
STATE ?= ops-log
DBT_BIN ?= dbt
DBT = cd dbt && DUCKDB_PATH=../$(DB) $(DBT_BIN)

.PHONY: all backfill incremental dbt backtest daily test fixture-all clean

all: backfill dbt backtest daily   ## real data: five-year backfill, backtest, one daily run

backfill:   ## NESO yearly CSVs from October 2021, NESO forecasts, Open-Meteo weather, bank holidays
	$(PY) ingestion/load.py backfill --db $(DB) --start 2021-10-01

incremental:   ## what the daily run does first: only data newer than each table's watermark
	$(PY) ingestion/load.py incremental --db $(DB)

dbt:
	$(DBT) build --profiles-dir .

backtest:   ## walk-forward monthly refits from April 2024; saves results/backtest_forecasts.parquet
	$(PY) forecasting/backtest.py --db $(DB) --start 2024-04-01
	$(PY) ops/state.py save-backtest --db $(DB)

daily:      ## the scheduled DAG: load, dbt, forecast tomorrow, dbt, report, save state
	$(PY) ops/run_daily.py --db $(DB) --state $(STATE)

test:
	FORECAST_DB=$(DB) FORECAST_STATE=$(STATE) $(PY) -m pytest -q tests

fixture-all:   ## synthetic bronze tables, offline: dbt, backtest, one daily run, tests (CI)
	$(PY) tests/fixtures/make_fixture.py --db warehouse/fixture.duckdb
	$(MAKE) dbt DB=warehouse/fixture.duckdb
	$(PY) forecasting/backtest.py --db warehouse/fixture.duckdb --start 2024-09-01
	$(PY) ops/run_daily.py --db warehouse/fixture.duckdb --state data/fixture/ops-log --offline --target 2025-01-01
	$(MAKE) test DB=warehouse/fixture.duckdb STATE=data/fixture/ops-log

clean:
	rm -rf warehouse dbt/target dbt/logs data/fixture
