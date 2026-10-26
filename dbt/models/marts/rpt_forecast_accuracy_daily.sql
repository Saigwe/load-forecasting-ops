-- Daily MAPE per method, with a 30-day rolling MAPE: what the morning report tracks over time. Live forecasts take
-- precedence over backtest ones for the same day and model.
with picked as (
    select *
    from {{ ref('fct_forecast_errors') }}
    qualify dense_rank() over (partition by method, settlement_date
                               order by case run_type when 'live' then 0 else 1 end) = 1
),
daily as (
    select method, any_value(run_type) as run_type, settlement_date, avg(ape) as mape, count(*) as half_hours,
           max(abs(error_mw)) as max_abs_error_mw
    from picked
    group by method, settlement_date
)
select
    *,
    avg(mape) over (partition by method order by settlement_date rows between 29 preceding and current row) as mape_30d
from daily
