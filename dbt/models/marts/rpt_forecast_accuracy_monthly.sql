-- MAPE and bias by month and method, BACKTEST AND PUBLISHED forecasts only, on the half hours every method forecast
-- (a fair, like-for-like comparison). Live forecasts are tracked daily in rpt_forecast_accuracy_daily.
with scored as (select * from {{ ref('fct_forecast_errors') }} where run_type <> 'live'),
covered as (
    select settlement_date, settlement_period
    from scored
    group by 1, 2
    having count(distinct method) = (select count(distinct method) from scored)
)
select
    e.method,
    cast(date_trunc('month', e.settlement_date) as date)                as month,
    count(*)                                                            as half_hours,
    avg(e.ape)                                                          as mape,
    avg(e.error_mw)                                                     as bias_mw,
    avg(abs(e.error_mw))                                                as mae_mw
from scored e
join covered c using (settlement_date, settlement_period)
group by 1, 2
