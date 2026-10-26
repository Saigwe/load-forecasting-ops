-- A day-ahead forecast must be issued before its target day starts. Issue times are UK local clock times (as NESO
-- publishes them), so the comparison is with local midnight. Catches leakage in the backtest and late live runs.
select method, settlement_date, settlement_period, issued_at
from {{ ref('fct_forecast_errors') }}
where issued_at is not null
  and issued_at >= cast(settlement_date as timestamp)
