{{ config(materialized='table') }}

-- Подаспекты по дням: число размеченных отзывов с аспектом и из них по знаку, плюс знаменатели дня из review_labeling_daily
with counts as (
    select app_id, day, llm_config_sk, category_id, aspect_id,
           count(*) as review_count,
           count(*) filter (where sentiment = '+') as positive_count,
           count(*) filter (where sentiment = '-') as negative_count,
           count(*) filter (where sentiment = '±') as mixed_count
    from {{ ref('review_aspect_tag') }}
    group by app_id, day, llm_config_sk, category_id, aspect_id
)
select c.*,
       d.review_count as day_review_count,
       d.content_count as day_content_count,
       d.labeled_count as day_labeled_count
from counts c
join {{ ref('review_labeling_daily') }} d
  on d.app_id = c.app_id and d.day = c.day and d.llm_config_sk = c.llm_config_sk
