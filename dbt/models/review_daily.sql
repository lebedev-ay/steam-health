{{ config(materialized='table') }}

select
    app_id,
    created_at::date as day,
    count(*) as review_count,
    count(*) filter (where voted_up) as positive_count
from {{ ref('review_flat') }}
group by app_id, created_at::date