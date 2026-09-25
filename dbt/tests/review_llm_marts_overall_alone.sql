-- overall_impression в витрине - только отзывы, где он единственный аспект: число в витрине сверяется с пересчётом по core
with alone as (
    select r.app_id, r.day, r.llm_config_sk, count(*) as n
    from {{ ref('review_labeled') }} r
    join {{ source('core', 'fct_review_aspect') }} t on t.labeling_sk = r.labeling_sk
    join {{ source('core', 'dim_aspect') }} a on a.aspect_sk = t.aspect_sk
    group by r.app_id, r.day, r.llm_config_sk, r.labeling_sk
    having count(*) = 1 and max(a.aspect_id) = 'overall_impression'
),
expected as (
    select app_id, day, llm_config_sk, sum(n) as n
    from alone
    group by app_id, day, llm_config_sk
),
mart as (
    select app_id, day, llm_config_sk, review_count as n
    from {{ ref('review_aspect_daily') }}
    where aspect_id = 'overall_impression'
)
select coalesce(e.app_id, m.app_id) as app_id, coalesce(e.day, m.day) as day,
       coalesce(e.llm_config_sk, m.llm_config_sk) as llm_config_sk, e.n as expected, m.n as in_mart
from expected e
full join mart m on m.app_id = e.app_id and m.day = e.day and m.llm_config_sk = e.llm_config_sk
where e.n is distinct from m.n
