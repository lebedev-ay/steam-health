{{ config(materialized='view') }}

select
    game_sk,
    app_id,
    game_name,
    app_type,
    is_free,
    metacritic_score,
    release_date_parsed,
    collection_status
from {{ source('core', 'dim_game') }}
where is_current
  and app_id > 0
