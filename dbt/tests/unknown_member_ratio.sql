-- доля строк с game_sk = -1 (заглушка Unknown) в core.fct_review
-- и core.fct_patch. Штатного источника таких строк больше нет:
-- load_fct_patch.py больше не грузит в fct_patch фид платформы.
-- Резкий рост доли — признак того, что загрузчики отработали
-- в неверном порядке (fct_review/fct_patch раньше dim_game).
-- Порог — переменная unknown_member_max_ratio в dbt_project.yml
with ratios as (
    select 'core.fct_review' as table_name,
           count(*) filter (where game_sk = -1)::numeric / nullif(count(*), 0) as ratio
    from {{ source('core', 'fct_review') }}

    union all

    select 'core.fct_patch' as table_name,
           count(*) filter (where game_sk = -1)::numeric / nullif(count(*), 0) as ratio
    from {{ source('core', 'fct_patch') }}
)
select table_name, ratio
from ratios
where ratio > {{ var('unknown_member_max_ratio') }}
