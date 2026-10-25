-- Baseline to beat: forecast each day's average demand with the same weekday last week.
with f as (
    select
        demand_date,
        avg_mw,
        lag(avg_mw, 7) over (order by demand_date) as forecast_mw
    from {{ ref('rpt_daily_demand') }}
)

select
    cast({{ dbt.date_trunc('month', 'demand_date') }} as date)       as forecast_month,
    count(*)                                                        as days_scored,
    100.0 * avg(abs(avg_mw - forecast_mw) / avg_mw)                 as mape_pct
from f
where forecast_mw is not null
group by 1
