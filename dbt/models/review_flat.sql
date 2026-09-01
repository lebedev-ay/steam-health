{{ config(materialized='table') }}

SELECT g.app_id,
       r.recommendation_id AS review_id,
       r.created_at,
       r.is_voted_up AS voted_up,
       l.language_code,
       r.created_at::date AS created_date
FROM {{ source('core', 'fct_review') }} r
JOIN {{ source('core', 'dim_game') }} g ON g.game_sk = r.game_sk
JOIN {{ source('core', 'dim_language') }} l ON l.language_sk = r.language_sk