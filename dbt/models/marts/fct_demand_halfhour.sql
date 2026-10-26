-- One row per settlement period: demand, calendar, weather (actual and day-ahead forecast), NESO's own day-ahead
-- forecast, and the naive baseline (the same period seven days earlier). The input to the forecast models.
select
    d.settlement_date,
    d.settlement_period,
    d.period_start_utc,
    d.nd_mw,
    d.embedded_wind_mw,
    d.embedded_solar_mw,
    extract(dow from d.settlement_date)                                 as day_of_week,
    extract(month from d.settlement_date)                               as month,
    extract(doy from d.settlement_date)                                 as day_of_year,
    h.holiday_date is not null                                          as is_bank_holiday,
    w.temp_actual_c, w.solar_actual_wm2, w.wind_actual_kmh,
    w.temp_forecast_c, w.solar_forecast_wm2, w.wind_forecast_kmh,
    n.neso_forecast_mw,
    n.published_at                                                      as neso_published_at,
    lag7.nd_mw                                                          as naive_forecast_mw
from {{ ref('stg_demand') }} d
left join {{ source('bronze', 'bank_holidays') }} h
  on h.holiday_date = d.settlement_date and h.region = 'england-and-wales'
left join {{ ref('stg_weather') }} w on w.hour_utc = date_trunc('hour', d.period_start_utc)
left join {{ source('bronze', 'neso_forecast') }} n
  on n.target_date = d.settlement_date and n.settlement_period = d.settlement_period
left join {{ ref('stg_demand') }} lag7
  on lag7.settlement_date = d.settlement_date - interval 7 day and lag7.settlement_period = d.settlement_period
