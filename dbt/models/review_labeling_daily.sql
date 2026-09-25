{{ config(materialized='table') }}

-- Знаменатели дня для долей аспектов: всего отзывов, из них содержательных (текст не короче порога), из них размеченных конфигурацией.
-- Строки есть у каждого дня игры для каждой конфигурации, которая размечала эту игру: день без разметки даёт labeled_count = 0, а не пропуск
with reviews as (
    select g.app_id,
           (f.created_at at time zone 'utc')::date as day,
           -- длина считается по всем отзывам: порог - переменная, пересчитать заранее нельзя
           char_length(btrim(coalesce(t.review_body, ''))) >= {{ var('llm_min_length') }} as is_content
    from {{ source('core', 'fct_review') }} f
    join {{ source('core', 'dim_game') }} g on g.game_sk = f.game_sk
    left join {{ source('core', 'review_text') }} t on t.review_sk = f.review_sk
    where g.app_id > 0
),
days as (
    select app_id, day,
           count(*) as review_count,
           count(*) filter (where is_content) as content_count
    from reviews
    group by app_id, day
),
labeled as (
    select app_id, day, llm_config_sk, count(*) as labeled_count
    from {{ ref('review_labeled') }}
    group by app_id, day, llm_config_sk
),
configs as (
    select distinct app_id, llm_config_sk from labeled
)
select d.app_id,
       d.day,
       c.llm_config_sk,
       d.review_count,
       d.content_count,
       coalesce(l.labeled_count, 0) as labeled_count
from days d
join configs c on c.app_id = d.app_id
left join labeled l on l.app_id = d.app_id and l.day = d.day and l.llm_config_sk = c.llm_config_sk
