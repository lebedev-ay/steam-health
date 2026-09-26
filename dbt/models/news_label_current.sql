{{ config(materialized='view') }}

-- Текущая разметка новости: самая свежая успешная разметка активной конфигурацией, одна строка на gid.
-- Активная конфигурация - модель и начало хэша промпта из переменных, как у разметки отзывов. Пока новости не размечались,
-- представление пустое, и дашборд считает важность событий по-старому: по типу, весу и отклику в отзывах
select distinct on (l.gid)
       l.gid,
       l.tier,
       l.kind,
       l.is_future,
       l.title_ru,
       l.llm_config_sk,
       l.labeled_at
from {{ source('core', 'fct_news_label') }} l
join {{ source('core', 'dim_llm_config') }} c on c.llm_config_sk = l.llm_config_sk
where l.status = 'labeled'
  and c.model = '{{ var("llm_news_model") }}'
  {% if var("llm_news_prompt_hash") %}
  and c.prompt_hash like '{{ var("llm_news_prompt_hash") }}%'
  {% else %}
  -- хэш не задан: like '%' выбрал бы любую конфигурацию этой модели, а разметка ещё не выбрана
  and false
  {% endif %}
order by l.gid, l.labeled_at desc, l.news_label_sk desc
