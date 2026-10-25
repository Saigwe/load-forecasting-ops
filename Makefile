PY ?= python
DB ?= warehouse/load_forecasting_ops.duckdb
DBT = cd dbt && DUCKDB_PATH=../$(DB) dbt

.PHONY: fixture-all bronze-fixture dbt clean

fixture-all: bronze-fixture dbt   ## synthetic fixture, no download (CI)

bronze-fixture:
	$(PY) tests/fixtures/make_fixture.py --db $(DB)

dbt:
	$(DBT) build --profiles-dir .

clean:
	rm -rf warehouse dbt/target dbt/logs
