-- Half-hourly GB national demand (ND, MW). Settlement periods count half hours from local midnight, so a day has 46
-- periods when clocks go forward and 50 when they go back; period_start_utc places each one on the real clock
-- (the dbt session runs in UTC: see profiles.yml).
select
    settlement_date,
    cast(settlement_period as integer)                                  as settlement_period,
    cast(timezone('Europe/London', cast(settlement_date as timestamp))
         + (cast(settlement_period as integer) - 1) * interval 30 minute as timestamp) as period_start_utc,
    cast(nd as double)                                                  as nd_mw,
    cast(tsd as double)                                                 as tsd_mw,
    cast(embedded_wind_generation as double)                            as embedded_wind_mw,
    cast(embedded_solar_generation as double)                           as embedded_solar_mw
from {{ source('bronze', 'demand') }}
