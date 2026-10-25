select
    settlement_ts,
    demand_mw
from {{ source('bronze', 'demand') }}
