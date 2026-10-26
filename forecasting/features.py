"""Features for a day-ahead forecast of GB national demand, built only from what is known at 09:45 the day before
(when NESO publishes its own day-ahead forecast), so the comparison with NESO is fair:

  lags        demand in the same settlement period 2, 7 and 14 days earlier; the average of 00:00-08:00 the day
              before (the latest demand known at 09:45) and of the same window two days before
  calendar    settlement period, day of week, time of year (sine/cosine), bank holiday on the day or a week earlier,
              and a trend term (rooftop solar keeps growing, pulling demand down)
  weather     temperature, solar radiation and wind for the target half hour AS FORECAST the day before; training
              rows from before forecasts exist (March 2024) use the weather that happened instead
  neso        (residual model only) NESO's own day-ahead forecast, public at 09:45 the day before
"""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

FEATURES = ["settlement_period", "day_of_week", "doy_sin", "doy_cos", "is_bank_holiday", "holiday_last_week", "trend_days",
            "nd_lag2", "nd_lag7", "nd_lag14", "d1_morning_mw", "d2_morning_mw", "morning_change",
            "temp_c", "solar_wm2", "wind_kmh", "heating_degrees"]
RESIDUAL_FEATURES = FEATURES + ["neso_forecast_mw", "neso_vs_lag7"]
EPOCH = pd.Timestamp("2021-10-01")


def frame(con: duckdb.DuckDBPyConnection, recent_outturn: bool = False) -> pd.DataFrame:
    """One row per settlement period with features and target. With recent_outturn, demand missing from NESO's
    historic file (it lags about three weeks) is filled from the forecast-performance feed's outturn."""
    d = con.execute("""
        select settlement_date, settlement_period, nd_mw, day_of_week, day_of_year, is_bank_holiday,
               temp_actual_c, solar_actual_wm2, wind_actual_kmh, temp_forecast_c, solar_forecast_wm2, wind_forecast_kmh,
               neso_forecast_mw
        from gold.fct_demand_halfhour
    """).df()
    if recent_outturn:
        extra = con.execute("""
            select n.target_date as settlement_date, n.settlement_period, n.neso_outturn_mw as nd_mw,
                   n.neso_forecast_mw
            from bronze.neso_forecast n
            where n.neso_outturn_mw is not null
              and (n.target_date, n.settlement_period) not in (select settlement_date, settlement_period from gold.fct_demand_halfhour)
        """).df()
        d = pd.concat([d, extra], ignore_index=True)
    d["settlement_date"] = pd.to_datetime(d.settlement_date)
    return d.sort_values(["settlement_date", "settlement_period"]).reset_index(drop=True)


def add_features(d: pd.DataFrame, weather: pd.DataFrame | None = None) -> pd.DataFrame:
    """Lags are joined by (date - k days, same period), never by row position, so clock-change days are handled."""
    base = d[["settlement_date", "settlement_period", "nd_mw"]]
    out = d.copy()
    for k in (2, 7, 14):
        lag = base.assign(settlement_date=base.settlement_date + pd.Timedelta(days=k)).rename(columns={"nd_mw": f"nd_lag{k}"})
        out = out.merge(lag, on=["settlement_date", "settlement_period"], how="left")
    morning = (base[base.settlement_period <= 16].groupby("settlement_date").nd_mw.mean().rename("m").reset_index())
    for k, name in ((1, "d1_morning_mw"), (2, "d2_morning_mw")):
        out = out.merge(morning.assign(settlement_date=morning.settlement_date + pd.Timedelta(days=k))
                        .rename(columns={"m": name}), on="settlement_date", how="left")
    out["morning_change"] = out.d1_morning_mw / out.d2_morning_mw - 1
    hol = out.groupby("settlement_date").is_bank_holiday.first().fillna(False)
    out["holiday_last_week"] = out.settlement_date.map(lambda x: bool(hol.get(x - pd.Timedelta(days=7), False)))
    out["is_bank_holiday"] = out.is_bank_holiday.fillna(False).astype(int)
    out["holiday_last_week"] = out.holiday_last_week.astype(int)
    doy = out.settlement_date.dt.dayofyear
    out["doy_sin"], out["doy_cos"] = np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)
    out["day_of_week"] = out.settlement_date.dt.dayofweek
    out["trend_days"] = (out.settlement_date - EPOCH).dt.days
    # weather as forecast the day before where it exists, otherwise what happened (training years only)
    for v, a, f in (("temp_c", "temp_actual_c", "temp_forecast_c"), ("solar_wm2", "solar_actual_wm2", "solar_forecast_wm2"),
                    ("wind_kmh", "wind_actual_kmh", "wind_forecast_kmh")):
        out[v] = out[f].fillna(out[a]) if f in out else out[a]
    out["heating_degrees"] = (15.5 - out.temp_c).clip(lower=0)
    out["neso_vs_lag7"] = out.neso_forecast_mw / out.nd_lag7 - 1
    return out
