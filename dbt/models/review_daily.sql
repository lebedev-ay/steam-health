{{ config(materialized='table') }}

-- Отзывы по дням: всего и положительных. Основа кривой настроения, детектора переломов и долей «не рекомендую» в выводах
select g.app_id,
       (f.created_at at time zone 'utc')::date as day,
       count(*) as review_count,
       count(*) filter (where f.is_voted_up) as positive_count
from {{ source('core', 'fct_review') }} f
join {{ source('core', 'dim_game') }} g on g.game_sk = f.game_sk
-- заглушка Unknown не игра: без фильтра отзывы без распознанной версии агрегировались бы отдельной "игрой" app_id = -1
where g.app_id > 0
group by g.app_id, (f.created_at at time zone 'utc')::date
