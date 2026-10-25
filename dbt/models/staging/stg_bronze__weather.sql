select
    cast(weather_date as date)           as weather_date,
    temp_c
from {{ source('bronze', 'weather') }}
