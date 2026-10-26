-- Daily view: energy, peak and when it happened, minimum, and the day's average temperature.
select
    settlement_date,
    count(*)                                                            as settlement_periods,
    sum(nd_mw) * 0.5 / 1000                                             as energy_gwh,
    max(nd_mw)                                                          as peak_mw,
    arg_max(settlement_period, nd_mw)                                   as peak_period,
    min(nd_mw)                                                          as min_mw,
    avg(temp_actual_c)                                                  as avg_temp_c,
    any_value(is_bank_holiday)                                          as is_bank_holiday
from {{ ref('fct_demand_halfhour') }}
group by 1
