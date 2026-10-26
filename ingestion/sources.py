"""Loaders for the three public sources, each idempotent (upsert on the natural key) and incremental where the
source allows it.

NESO data portal (CKAN, NESO Open Data Licence)
  demand     historic-demand-data: half-hourly national demand (ND), one CSV resource per year. `backfill` reads the
             yearly CSVs; `incremental` queries the datastore API for dates after the watermark (re-reading the last
             day, which NESO may revise).
  forecasts  day-ahead-half-hourly-demand-forecast-performance: NESO's own day-ahead forecast for each half hour
             (published 09:45 the day before) with the outturn, from April 2021.
Open-Meteo (CC BY 4.0)
  weather    hourly temperature, solar radiation and wind speed at nine GB cities: archive (what happened) and
             previous-runs day-1 forecasts (what was forecast the day before, from February 2024), averaged with
             population weights. Solar matters: rooftop solar is invisible to the grid and lowers midday demand.
GOV.UK
  holidays   bank holidays for England and Wales, and Scotland.
"""
from __future__ import annotations

import datetime as dt
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import duckdb
import pandas as pd

UA = "load-forecasting-ops/1.0 (+https://github.com/Saigwe/load-forecasting-ops)"
NESO = "https://api.neso.energy/api/3/action"
DEMAND_PACKAGE = "historic-demand-data"
FORECAST_RESOURCE = "08e41551-80f8-4e28-a416-ea473a695db9"
# Rough city populations (millions) as weights for a GB demand-weighted temperature; London dominates, as it should.
CITIES = {"London": (51.51, -0.13, 8.8), "Birmingham": (52.48, -1.90, 1.1), "Leeds": (53.80, -1.55, 0.8),
          "Glasgow": (55.86, -4.25, 0.6), "Manchester": (53.48, -2.24, 0.6), "Edinburgh": (55.95, -3.19, 0.5),
          "Bristol": (51.45, -2.59, 0.5), "Cardiff": (51.48, -3.18, 0.4), "Newcastle": (54.98, -1.61, 0.3)}


def get(url: str, retries: int = 4) -> bytes:
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=300) as r:
                return r.read()
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(5 * 2 ** attempt)


def upsert(con, table: str, df: pd.DataFrame, keys: list[str]) -> int:
    """Insert or replace rows by key, so re-running any load never duplicates."""
    if df.empty:
        return 0
    con.execute("create schema if not exists bronze")
    con.execute(f"create table if not exists bronze.{table} as select * from df limit 0")
    on = " and ".join(f"t.{k} = d.{k}" for k in keys)
    con.execute(f"delete from bronze.{table} t using df d where {on}")
    con.execute(f"insert into bronze.{table} by name select * from df")
    return len(df)


# ---- NESO demand ------------------------------------------------------------------------------------------------
DEMAND_COLS = ["SETTLEMENT_DATE", "SETTLEMENT_PERIOD", "ND", "TSD", "ENGLAND_WALES_DEMAND",
               "EMBEDDED_WIND_GENERATION", "EMBEDDED_SOLAR_GENERATION", "FORECAST_ACTUAL_INDICATOR"]


def demand_resources() -> dict[int, dict]:
    pkg = json.loads(get(f"{NESO}/package_show?id={DEMAND_PACKAGE}"))["result"]
    out = {}
    for r in pkg["resources"]:
        if r.get("format") == "CSV" and r["name"].startswith("Historic Demand Data "):
            out[int(r["name"].rsplit(" ", 1)[1])] = {"id": r["id"], "url": r["url"]}
    return out


def parse_settlement_date(col: pd.Series) -> pd.Series:
    """NESO's yearly files use three date formats (01-JAN-2021, 01-Jan-23, 2025-01-01). Parse each explicitly:
    a lenient day-first parser silently turns 2026-01-10 into 1 October."""
    text = col.astype(str).str.strip().str.strip('"')
    out = pd.Series(pd.NaT, index=col.index)
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y"):
        todo = out.isna()
        out[todo] = pd.to_datetime(text[todo].str.title(), format=fmt, errors="coerce")
    if out.isna().any():
        raise ValueError(f"unparsed settlement dates: {text[out.isna()].unique()[:5]}")
    return out.dt.date


def _demand_frame(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.upper() for c in df.columns]
    df = df[[c for c in DEMAND_COLS if c in df.columns]].copy()
    df["SETTLEMENT_DATE"] = parse_settlement_date(df.SETTLEMENT_DATE)
    df["FORECAST_ACTUAL_INDICATOR"] = df.get("FORECAST_ACTUAL_INDICATOR", "A")
    df = df[df.FORECAST_ACTUAL_INDICATOR.fillna("A").eq("A")]  # outturn only; NESO appends its own forecasts
    return df.rename(columns=str.lower).drop_duplicates(["settlement_date", "settlement_period"], keep="last")


def demand_backfill(con, raw: Path, start: dt.date) -> int:
    loaded = 0
    for year, res in sorted(demand_resources().items()):
        if year < start.year:
            continue
        path = raw / "neso" / f"demanddata_{year}.csv"
        if not path.exists() or year >= dt.date.today().year:  # the current year's file changes daily
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(get(res["url"]))
        df = _demand_frame(pd.read_csv(path))
        loaded += upsert(con, "demand", df[df.settlement_date >= start], ["settlement_date", "settlement_period"])
    return loaded


def demand_incremental(con) -> tuple[int, str]:
    watermark = con.execute("select max(settlement_date) from bronze.demand").fetchone()[0]
    resources = demand_resources()
    loaded = 0
    for year in sorted({watermark.year, dt.date.today().year}):
        if year not in resources:
            continue
        sql = (f'select * from "{resources[year]["id"]}" where "SETTLEMENT_DATE" >= \'{watermark.isoformat()}\'')
        records = json.loads(get(f"{NESO}/datastore_search_sql?sql={urllib.parse.quote(sql)}"))["result"]["records"]
        if records:
            loaded += upsert(con, "demand", _demand_frame(pd.DataFrame(records)), ["settlement_date", "settlement_period"])
    return loaded, watermark.isoformat()


# ---- NESO day-ahead forecasts -----------------------------------------------------------------------------------
def neso_forecasts(con) -> int:
    try:
        watermark = con.execute("select max(target_date) from bronze.neso_forecast").fetchone()[0]
    except duckdb.CatalogException:
        watermark = None
    where = f' where "Date" >= \'{watermark.isoformat()}\'' if watermark else ""
    rows, offset = [], 0
    while True:
        sql = f'select * from "{FORECAST_RESOURCE}"{where} order by "_id" limit 32000 offset {offset}'
        page = json.loads(get(f"{NESO}/datastore_search_sql?sql={urllib.parse.quote(sql)}"))["result"]["records"]
        rows += page
        if len(page) < 32000:
            break
        offset += len(page)
    if not rows:
        return 0
    df = pd.DataFrame(rows)
    out = pd.DataFrame({"target_date": pd.to_datetime(df.Date).dt.date, "settlement_period": df.Settlement_Period.astype(int),
                        "neso_forecast_mw": pd.to_numeric(df.Demand_Forecast), "neso_outturn_mw": pd.to_numeric(df.Demand_Outturn),
                        "published_at": pd.to_datetime(df.Publish_Datetime)})
    return upsert(con, "neso_forecast", out.drop_duplicates(["target_date", "settlement_period"], keep="last"),
                  ["target_date", "settlement_period"])


# ---- Open-Meteo weather -----------------------------------------------------------------------------------------
WEATHER_VARS = ["temperature_2m", "shortwave_radiation", "wind_speed_10m"]


def _om(base: str, start: dt.date, end: dt.date, suffix: str = "") -> pd.DataFrame:
    """Population-weighted GB average of each weather variable, hourly (UTC)."""
    lats = ",".join(str(c[0]) for c in CITIES.values())
    lons = ",".join(str(c[1]) for c in CITIES.values())
    names = [v + suffix for v in WEATHER_VARS]
    url = f"{base}?latitude={lats}&longitude={lons}&hourly={','.join(names)}&start_date={start}&end_date={end}&timezone=UTC"
    data = json.loads(get(url))
    frames = []
    for (_, (_, _, w)), loc in zip(CITIES.items(), data):
        frames.append(pd.DataFrame({"ts": pd.to_datetime(loc["hourly"]["time"]), "w": w,
                                    **{v: loc["hourly"][n] for v, n in zip(WEATHER_VARS, names)}}))
    df = pd.concat(frames).dropna()
    out = df.groupby("ts").apply(lambda g: pd.Series({v: (g[v] * g.w).sum() / g.w.sum() for v in WEATHER_VARS}),
                                 include_groups=False).reset_index()
    return out.rename(columns={"temperature_2m": "temp_c", "shortwave_radiation": "solar_wm2", "wind_speed_10m": "wind_kmh"})


def _years(start: dt.date, end: dt.date):
    for y in range(start.year, end.year + 1):
        s, e = max(start, dt.date(y, 1, 1)), min(end, dt.date(y, 12, 31))
        if s <= e:
            yield s, e


def _watermark(con, table: str, default: dt.date, back_days: int) -> dt.date:
    try:
        last = con.execute(f"select max(ts) from bronze.{table}").fetchone()[0]
        return max(default, (last - dt.timedelta(days=back_days)).date()) if last else default
    except duckdb.CatalogException:
        return default


def weather(con, start: dt.date, forecast_from: dt.date = dt.date(2024, 1, 1)) -> tuple[int, int]:
    """Actuals from the archive (about five days behind real time); day-ahead forecasts as issued the day before."""
    today = dt.date.today()
    a_start = _watermark(con, "weather_actual", start, 7)
    actual = [_om("https://archive-api.open-meteo.com/v1/archive", s, e)
              for s, e in _years(a_start, today - dt.timedelta(days=6))]
    n_a = upsert(con, "weather_actual", pd.concat(actual), ["ts"]) if actual else 0
    f_start = _watermark(con, "weather_forecast", forecast_from, 3)
    fc = [_om("https://previous-runs-api.open-meteo.com/v1/forecast", s, e, "_previous_day1")
          for s, e in _years(f_start, today + dt.timedelta(days=1))]
    n_f = upsert(con, "weather_forecast", pd.concat(fc), ["ts"]) if fc else 0
    return n_a, n_f


# ---- GOV.UK bank holidays ---------------------------------------------------------------------------------------
def holidays(con) -> int:
    data = json.loads(get("https://www.gov.uk/bank-holidays.json"))
    rows = [{"holiday_date": dt.date.fromisoformat(e["date"]), "region": region, "title": e["title"]}
            for region in ("england-and-wales", "scotland") for e in data[region]["events"]]
    return upsert(con, "bank_holidays", pd.DataFrame(rows), ["holiday_date", "region"])
