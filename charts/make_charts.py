"""README charts from the gold marts. Usage: python charts/make_charts.py [--db warehouse/load.duckdb] [--out docs/charts]

The committed charts come from the real NESO backfill plus the committed backtest (make backfill, state import, dbt).
CI renders them from the fixture warehouse to a temporary folder to prove the code still runs.
"""
import argparse
from pathlib import Path

import duckdb
import matplotlib.dates as mdates

import style as st

ROOT = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=str(ROOT / "warehouse" / "load.duckdb"))
ap.add_argument("--out", default=str(ROOT / "docs" / "charts"))
a = ap.parse_args()
OUT = Path(a.out)
con = duckdb.connect(a.db, read_only=True)

acc = con.execute("select method, month, mape from gold.rpt_forecast_accuracy_monthly order by month").fetchall()
methods = [("naive_last_week", "Naive: same day last week", st.MUTED, "--"),
           ("lgbm_day_ahead", "LightGBM standalone", st.S[3], "-"),
           ("neso_day_ahead", "NESO published forecast", st.S[1], "-"),
           ("lgbm_neso_residual", "NESO + learned error (this repo)", st.S[0], "-")]
f, ax = st.fig(8, 3.8)
for m, lab, col, ls in methods:
    pts = [(mo, v) for mm, mo, v in acc if mm == m]
    if pts:
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=col, ls=ls, lw=2 if m != "naive_last_week" else 1.4, label=lab)
st.fmt(ax, "y", "pct", 0)
ax.set_ylim(0, None)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
n = len({mo for _, mo, _ in acc})
st.head(ax, "Correcting NESO's own forecast beats it in most months",
        f"Day-ahead MAPE by month, walk-forward backtest over {n} months of GB national demand", legend=True, ncol=2)
st.save(f, OUT / "forecast_accuracy_monthly.png")

dd = con.execute("""select date_trunc('week', settlement_date) w, avg(energy_gwh), max(peak_mw)
                    from gold.rpt_daily_demand where settlement_periods >= 46 group by 1 order by 1""").fetchall()
f, ax = st.fig(8, 3.2)
ax.plot([r[0] for r in dd], [r[2] / 1000 for r in dd], color=st.S[0], lw=1.6, label="Weekly peak demand")
ax.set_ylabel("GW")
ax.set_ylim(0, None)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
st.head(ax, "GB national demand peaks every winter at about 45 GW",
        "Highest half-hour each week, NESO national demand (ND), real data")
st.save(f, OUT / "weekly_peak_demand.png")
print(f"wrote charts to {OUT}")
