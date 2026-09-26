{{ config(materialized='view') }}

-- Активная конфигурация выводов по переломам: модель и начало хэша промпта вывода (llm/prompts/verdict_*.txt) из переменных dbt,
-- как у llm_config_active для разметки. Ровно одна строка - тест llm_verdict_config_active_one_row
select llm_config_sk, model, prompt_name, prompt_hash, params
from {{ source('core', 'dim_llm_config') }}
where model = '{{ var("llm_verdict_model") }}'
  and prompt_hash like '{{ var("llm_verdict_prompt_hash") }}%'
