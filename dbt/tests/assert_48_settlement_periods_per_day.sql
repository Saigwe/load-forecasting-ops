-- Completeness: every day has 48 half-hour settlement periods (no clock-change days in the fixture).
select * from {{ ref('rpt_daily_demand') }} where settlement_periods <> 48
