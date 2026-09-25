{{ config(materialized='view') }}

-- Активная конфигурация разметки - та, по которой дашборд фильтрует витрины. Задаётся естественным ключом (модель + начало хэша промпта),
-- а не llm_config_sk: суррогатный ключ на разных стендах разный. Ровно одна строка - тест llm_config_active_one_row
select llm_config_sk, model, prompt_name, codebook_version, prompt_hash, params
from {{ source('core', 'dim_llm_config') }}
where model = '{{ var("llm_active_model") }}'
  and prompt_hash like '{{ var("llm_active_prompt_hash") }}%'
