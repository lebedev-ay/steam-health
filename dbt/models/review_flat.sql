{{ config(materialized='table') }}

select g.app_id,
       r.recommendation_id as review_id,
       r.created_at,
       r.is_voted_up as voted_up,
       l.language_code,
       (r.created_at at time zone 'utc')::date as created_date
from {{ source('core', 'fct_review') }} r
join {{ source('core', 'dim_game') }} g on g.game_sk = r.game_sk
join {{ source('core', 'dim_language') }} l on l.language_sk = r.language_sk
-- заглушка Unknown не игра: без фильтра отзывы без распознанной версии уезжают в витрину как app_id = -1 и агрегируются отдельной "игрой"
where g.app_id > 0