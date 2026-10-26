-- Hourly weather (UTC), actual and as forecast the day before, side by side.
select
    coalesce(a.ts, f.ts)                                                as hour_utc,
    a.temp_c                                                            as temp_actual_c,
    a.solar_wm2                                                         as solar_actual_wm2,
    a.wind_kmh                                                          as wind_actual_kmh,
    f.temp_c                                                            as temp_forecast_c,
    f.solar_wm2                                                         as solar_forecast_wm2,
    f.wind_kmh                                                          as wind_forecast_kmh
from {{ source('bronze', 'weather_actual') }} a
full join {{ source('bronze', 'weather_forecast') }} f using (ts)
