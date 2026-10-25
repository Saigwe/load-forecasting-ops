"""Generate a small synthetic fixture from tests/fixtures/fixture_spec.yml into DuckDB `bronze`.

The fixture lets CI run the whole pipeline without downloading the real dataset. It has the
same table and column names as the real-data load. Tables are built in the order listed, so a
table can reference any table above it.

Column types
- id        prefix + zero-padded sequence                  {type: id, prefix: C}
- fk        random key from an earlier table               {type: fk, table: customers, column: customer_id, unique: false}
- int       uniform integer, inclusive                     {type: int, low: 1, high: 10}
- float     uniform or lognormal, rounded                  {type: float, low: 0, high: 1} | {type: float, dist: lognormal, mean: 3, sigma: 1}
- choice    pick from values, optional weights             {type: choice, values: [a, b], p: [0.8, 0.2]}
- bool      true with probability p                        {type: bool, p: 0.1}
- date      uniform date (midnight timestamp)              {type: date, start: 2025-01-01, end: 2025-06-30}
- timestamp uniform timestamp                              {type: timestamp, start: 2025-01-01, end: 2025-06-30}
- expr      a Python expression over df, tables, rng, n, np, pd
Any column can add `null_p` (share of nulls). Columns with `drop: true` are helpers and are not saved.

Table options
- rows: N                         number of rows
- grid: {parent: t.col, start, end, freq, column}   one row per parent key x date in pd.date_range
- data: {columns: [...], rows: [[...], ...]}        fixed reference rows
- duplicate: {rows, id_column, shift_column, shift_minutes}   copies rows (id + 'D'), to test dedup/controls
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent


def make_column(name: str, spec: dict, n: int, df: pd.DataFrame, tables: dict, rng: np.random.Generator):
    kind = spec["type"]
    if kind == "id":
        width = spec.get("width", 6)
        return [f"{spec['prefix']}{i:0{width}d}" for i in range(1, n + 1)]
    if kind == "fk":
        keys = tables[spec["table"]][spec["column"]].dropna().to_numpy()
        return rng.choice(keys, size=n, replace=not spec.get("unique", False))
    if kind == "int":
        return rng.integers(spec["low"], spec["high"] + 1, size=n)
    if kind == "float":
        if spec.get("dist") == "lognormal":
            values = rng.lognormal(spec["mean"], spec["sigma"], n)
        else:
            values = rng.uniform(spec["low"], spec["high"], n)
        return np.round(values, spec.get("decimals", 2))
    if kind == "choice":
        return rng.choice(spec["values"], size=n, p=spec.get("p"))
    if kind == "bool":
        return rng.random(n) < spec["p"]
    if kind in ("date", "timestamp"):
        start, end = pd.Timestamp(spec["start"]), pd.Timestamp(spec["end"])
        span = int((end - start).total_seconds())
        offsets = rng.integers(0, span + 1, size=n)
        values = start + pd.to_timedelta(offsets, unit="s")
        return values.normalize() if kind == "date" else values
    if kind == "expr":
        return eval(spec["expr"], {"np": np, "pd": pd}, {"df": df, "tables": tables, "rng": rng, "n": n})
    raise ValueError(f"{name}: unknown column type {kind!r}")


def build_table(spec: dict, tables: dict, rng: np.random.Generator) -> pd.DataFrame:
    if "data" in spec:
        return pd.DataFrame(spec["data"]["rows"], columns=spec["data"]["columns"])

    if "grid" in spec:
        g = spec["grid"]
        dates = pd.date_range(g["start"], g["end"], freq=g["freq"])
        if "parent" in g:
            table, col = g["parent"].split(".")
            keys = tables[table][col].to_numpy()
            df = pd.DataFrame({col: np.repeat(keys, len(dates)), g["column"]: np.tile(dates, len(keys))})
        else:
            df = pd.DataFrame({g["column"]: dates})
    else:
        df = pd.DataFrame(index=range(spec["rows"]))

    n = len(df)
    for name, col in (spec.get("columns") or {}).items():
        values = make_column(name, col, n, df, tables, rng)
        df[name] = pd.Series(values, index=df.index) if not isinstance(values, pd.Series) else values.to_numpy()
        if col.get("null_p"):
            df.loc[rng.random(n) < col["null_p"], name] = None

    if "duplicate" in spec:
        d = spec["duplicate"]
        dup = df.sample(d["rows"], random_state=int(rng.integers(1_000_000_000))).copy()
        if d.get("id_column"):
            dup[d["id_column"]] = dup[d["id_column"]] + "D"
        if d.get("shift_column"):
            dup[d["shift_column"]] = dup[d["shift_column"]] + pd.to_timedelta(d.get("shift_minutes", 1), unit="m")
        for col, jitter in (d.get("jitter") or {}).items():
            dup[col] = np.round(dup[col] * (1 + rng.normal(0, jitter, len(dup))), 2)
        df = pd.concat([df, dup], ignore_index=True)

    helpers = [name for name, col in (spec.get("columns") or {}).items() if col.get("drop")]
    return df.drop(columns=helpers)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--spec", default=str(HERE / "fixture_spec.yml"))
    args = ap.parse_args()

    spec = yaml.safe_load(Path(args.spec).read_text(encoding="utf-8"))
    rng = np.random.default_rng(spec.get("seed", 42))
    tables: dict[str, pd.DataFrame] = {}
    for table in spec["tables"]:
        tables[table["name"]] = build_table(table, tables, rng)

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(args.db) as con:
        con.execute("create schema if not exists bronze")
        for name, df in tables.items():
            con.register("df", df)
            con.execute(f"create or replace table bronze.{name} as select * from df")
            con.unregister("df")
            print(f"bronze.{name:<28} {len(df):>9,} rows")


if __name__ == "__main__":
    main()
