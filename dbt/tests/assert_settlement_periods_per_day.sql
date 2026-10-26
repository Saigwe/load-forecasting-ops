-- A settlement day has 48 periods, except the clock-change Sundays: 46 on the last Sunday of March, 50 on the last
-- Sunday of October. The latest day may be partial while NESO is still publishing it.
with days as (
    select settlement_date, count(*) as periods, max(settlement_period) as last_period
    from {{ ref('stg_demand') }}
    group by 1
),
expected as (
    select settlement_date, periods,
           case when extract(dow from settlement_date) = 0 and extract(month from settlement_date) = 3
                     and extract(day from settlement_date) > 24 then 46
                when extract(dow from settlement_date) = 0 and extract(month from settlement_date) = 10
                     and extract(day from settlement_date) > 24 then 50
                else 48 end as expected_periods
    from days
    where settlement_date < (select max(settlement_date) from days)
)
select * from expected where periods <> expected_periods
