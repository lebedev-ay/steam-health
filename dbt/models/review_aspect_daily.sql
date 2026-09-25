{{ config(materialized='table') }}

-- Подаспекты по дням: число размеченных отзывов с аспектом и из них по знаку, плюс знаменатели дня из review_labeling_daily.
-- overall_impression засчитывается, только если это единственный аспект отзыва: правило «только без конкретики» применяется здесь, исходная разметка в core не меняется
with tags as (
    select r.app_id, r.day, r.llm_config_sk, r.labeling_sk,
           a.category_id, a.aspect_id, t.sentiment,
           count(*) over (partition by t.labeling_sk) as review_aspects
    from {{ ref('review_labeled') }} r
    join {{ source('core', 'fct_review_aspect') }} t on t.labeling_sk = r.labeling_sk
    join {{ source('core', 'dim_aspect') }} a on a.aspect_sk = t.aspect_sk
),
per_review as (
    -- повториться в отзыве может только other с разными метками: знак сворачивается так же, как в review_category_daily
    select app_id, day, llm_config_sk, labeling_sk, category_id, aspect_id,
           case when min(sentiment) = max(sentiment) then min(sentiment) else '±' end as sentiment
    from tags
    where aspect_id <> 'overall_impression' or review_aspects = 1
    group by app_id, day, llm_config_sk, labeling_sk, category_id, aspect_id
),
counts as (
    select app_id, day, llm_config_sk, category_id, aspect_id,
           count(*) as review_count,
           count(*) filter (where sentiment = '+') as positive_count,
           count(*) filter (where sentiment = '-') as negative_count,
           count(*) filter (where sentiment = '±') as mixed_count
    from per_review
    group by app_id, day, llm_config_sk, category_id, aspect_id
)
select c.*,
       d.day_review_count,
       d.day_content_count,
       d.day_labeled_count
from counts c
join (
    select app_id, day, llm_config_sk,
           review_count as day_review_count,
           content_count as day_content_count,
           labeled_count as day_labeled_count
    from {{ ref('review_labeling_daily') }}
) d on d.app_id = c.app_id and d.day = c.day and d.llm_config_sk = c.llm_config_sk
