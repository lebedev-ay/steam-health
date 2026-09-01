{{ config(materialized='view') }}

SELECT
    game_sk,
    app_id,
    game_name,
    app_type,
    is_free,
    metacritic_score,
    release_date_parsed,
    collection_status
FROM {{ source('core', 'dim_game') }}
WHERE is_current
  AND app_id > 0


  