select
    cast(d.settlement_ts as date)   as demand_date,
    count(*)                        as settlement_periods,
    max(d.demand_mw)                as peak_mw,
    avg(d.demand_mw)                as avg_mw,
    min(d.demand_mw)                as min_mw,
    max(w.temp_c)                   as temp_c
from {{ ref('stg_bronze__demand') }} d
left join {{ ref('stg_bronze__weather') }} w on w.weather_date = cast(d.settlement_ts as date)
group by 1
