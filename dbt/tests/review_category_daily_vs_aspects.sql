-- категория считает разные отзывы: не меньше самого частого подаспекта категории и не больше суммы подаспектов
with aspects as (
    select app_id, day, llm_config_sk, category_id,
           max(review_count) as max_aspect, sum(review_count) as sum_aspects
    from {{ ref('review_aspect_daily') }}
    group by app_id, day, llm_config_sk, category_id
)
select c.app_id, c.day, c.llm_config_sk, c.category_id, c.review_count, a.max_aspect, a.sum_aspects
from {{ ref('review_category_daily') }} c
full join aspects a
  on a.app_id = c.app_id and a.day = c.day and a.llm_config_sk = c.llm_config_sk and a.category_id = c.category_id
where c.review_count is null or a.max_aspect is null
   or c.review_count < a.max_aspect or c.review_count > a.sum_aspects
