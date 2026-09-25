{{ config(materialized='view') }}

-- Размеченные отзывы, одна строка на (recommendation_id, llm_config_sk): основа витрин LLM-разметки.
-- Разметка засчитывается, только если размечен текущий текст отзыва (хэш версии совпадает с core.review_text) и он не короче порога:
-- так размеченные всегда подмножество содержательных, а отзыв, исправленный после разметки, выпадает до переразметки
select g.app_id,
       (f.created_at at time zone 'utc')::date as day,
       f.recommendation_id,
       l.llm_config_sk,
       l.labeling_sk
from {{ source('core', 'fct_review_labeling') }} l
join {{ source('core', 'review_text_version') }} v on v.review_text_sk = l.review_text_sk and v.is_current
join {{ source('core', 'fct_review') }} f on f.recommendation_id = v.recommendation_id
join {{ source('core', 'dim_game') }} g on g.game_sk = f.game_sk
join {{ source('core', 'review_text') }} t on t.review_sk = f.review_sk
where l.status in ('labeled', 'no_opinion')
  and g.app_id > 0
  and v.text_hash = md5(coalesce(t.review_body, ''))
  and char_length(btrim(coalesce(t.review_body, ''))) >= {{ var('llm_min_length') }}
