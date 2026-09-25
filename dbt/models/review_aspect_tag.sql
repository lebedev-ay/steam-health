{{ config(materialized='view') }}

-- Теги размеченных отзывов, одна строка на (labeling_sk, aspect_id): общая основа review_aspect_daily и review_category_daily.
-- overall_impression остаётся, только если это единственный аспект отзыва: правило «только без конкретики» применяется здесь, исходная разметка в core не меняется
with tags as (
    select r.app_id, r.day, r.llm_config_sk, r.labeling_sk,
           a.category_id, a.aspect_id, t.sentiment,
           count(*) over (partition by t.labeling_sk) as review_aspects
    from {{ ref('review_labeled') }} r
    join {{ source('core', 'fct_review_aspect') }} t on t.labeling_sk = r.labeling_sk
    join {{ source('core', 'dim_aspect') }} a on a.aspect_sk = t.aspect_sk
)
-- повториться в отзыве может только other с разными метками. Разные знаки сворачиваются в «±» - так же, как в категории
select app_id, day, llm_config_sk, labeling_sk, category_id, aspect_id,
       {{ fold_sentiment('sentiment') }} as sentiment
from tags
where aspect_id <> 'overall_impression' or review_aspects = 1
group by app_id, day, llm_config_sk, labeling_sk, category_id, aspect_id
