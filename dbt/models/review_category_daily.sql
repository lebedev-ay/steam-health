{{ config(materialized='table') }}

-- Категории по дням: число разных отзывов с хотя бы одним аспектом категории. Складывать подаспекты нельзя - отзыв с двумя подаспектами категории посчитался бы дважды.
-- Знак считается по отзыву: все аспекты категории с одним знаком - этот знак, разные - «±»
with review_category as (
    select app_id, day, llm_config_sk, labeling_sk, category_id,
           {{ fold_sentiment('sentiment') }} as sentiment
    from {{ ref('review_aspect_tag') }}
    group by app_id, day, llm_config_sk, labeling_sk, category_id
),
counts as (
    select app_id, day, llm_config_sk, category_id,
           count(*) as review_count,
           count(*) filter (where sentiment = '+') as positive_count,
           count(*) filter (where sentiment = '-') as negative_count,
           count(*) filter (where sentiment = '±') as mixed_count
    from review_category
    group by app_id, day, llm_config_sk, category_id
)
select c.*,
       d.review_count as day_review_count,
       d.content_count as day_content_count,
       d.labeled_count as day_labeled_count
from counts c
join {{ ref('review_labeling_daily') }} d
  on d.app_id = c.app_id and d.day = c.day and d.llm_config_sk = c.llm_config_sk
