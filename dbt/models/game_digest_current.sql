{{ config(materialized='view') }}

-- Текущая сводка месяца по игре: одна строка на (app_id, period_from) - самая свежая сводка по активной конфигурации разметки.
-- Берётся независимо от checks_passed: прежняя сводка, прошедшая проверку, сделана по устаревшим уликам. Показывать ли текст, решает дашборд
select distinct on (d.app_id, d.period_from)
       d.digest_sk,
       d.app_id,
       d.period_from,
       d.period_to,
       d.llm_config_sk,
       d.headline,
       d.summary,
       d.checks_passed,
       d.created_at
from {{ source('core', 'fct_game_digest') }} d
join {{ ref('llm_config_active') }} l on l.llm_config_sk = d.labeling_config_sk
order by d.app_id, d.period_from, d.created_at desc, d.digest_sk desc
