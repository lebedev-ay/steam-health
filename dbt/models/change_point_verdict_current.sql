{{ config(materialized='view') }}

-- Текущий вывод по точке перелома: одна строка на (app_id, change_date) - самый свежий вывод активной конфигурации генерации
-- по активной конфигурации разметки. Берётся независимо от checks_passed: прежний вывод, прошедший проверку, не подставляется -
-- он сделан по устаревшим уликам. Показывать ли текст, дашборд решает по checks_passed
select distinct on (v.app_id, v.change_date)
       v.verdict_sk,
       v.app_id,
       v.change_date,
       v.before_from,
       v.after_to,
       v.llm_config_sk,
       v.labeling_config_sk,
       v.author,
       v.status,
       v.what_happened,
       v.what_players_say,
       v.excerpts,
       v.support_numbers,
       v.checks_passed,
       v.checks,
       v.detector_shift_pp,
       v.evidence,
       v.evidence_hash,
       v.created_at
from {{ source('core', 'fct_change_point_verdict') }} v
join {{ ref('llm_verdict_config_active') }} g on g.llm_config_sk = v.llm_config_sk
join {{ ref('llm_config_active') }} l on l.llm_config_sk = v.labeling_config_sk
order by v.app_id, v.change_date, v.created_at desc, v.verdict_sk desc
