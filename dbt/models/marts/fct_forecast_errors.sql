-- Every forecast we can score, per settlement period and method, against national demand outturn:
--   our models (bronze.model_forecasts), NESO's published day-ahead forecast, and the naive same-day-last-week.
-- Outturn comes from NESO's historic demand file, or for the latest weeks (the file lags about three weeks) from
-- NESO's forecast-performance feed, which has outturn up to this morning. The naive baseline uses the same actuals.
with actuals as (
    select coalesce(d.settlement_date, o.target_date) as settlement_date,
           coalesce(d.settlement_period, o.settlement_period) as settlement_period,
           coalesce(d.nd_mw, o.neso_outturn_mw) as actual_mw
    from {{ ref('stg_demand') }} d
    full join (select * from {{ source('bronze', 'neso_forecast') }} where neso_outturn_mw is not null) o
      on o.target_date = d.settlement_date and o.settlement_period = d.settlement_period
),
forecasts as (
    select model as method, target_date as settlement_date, settlement_period, forecast_mw, issued_at,
           case when run_id like 'live-%' then 'live' else 'backtest' end as run_type
    from {{ source('bronze', 'model_forecasts') }}
    union all
    select 'neso_day_ahead', target_date, settlement_period, neso_forecast_mw, published_at, 'published'
    from {{ source('bronze', 'neso_forecast') }} where neso_forecast_mw is not null
    union all
    select 'naive_last_week', a.settlement_date, a.settlement_period, l.actual_mw, null, 'baseline'
    from actuals a
    join actuals l on l.settlement_date = a.settlement_date - interval 7 day and l.settlement_period = a.settlement_period
)
select
    f.method,
    f.run_type,
    f.settlement_date,
    f.settlement_period,
    f.issued_at,
    f.forecast_mw,
    a.actual_mw,
    f.forecast_mw - a.actual_mw                                         as error_mw,
    abs(f.forecast_mw - a.actual_mw) / a.actual_mw                      as ape
from forecasts f
join actuals a using (settlement_date, settlement_period)
where a.actual_mw > 0
