-- overall_impression в витринах - только отзывы, где он единственный аспект: подаспект и категория overall сверяются с пересчётом по core
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
marts as (
    select 'review_aspect_daily' as mart, app_id, day, llm_config_sk, review_count as n
    from {{ ref('review_aspect_daily') }}
    where aspect_id = 'overall_impression'
    union all
    select 'review_category_daily', app_id, day, llm_config_sk, review_count
    from {{ ref('review_category_daily') }}
    where category_id = 'overall'
),
checks as (
    select m.mart, e.app_id, e.day, e.llm_config_sk, e.n
    from expected e
    cross join (values ('review_aspect_daily'), ('review_category_daily')) as m (mart)
)
select coalesce(c.mart, m.mart) as mart, coalesce(c.app_id, m.app_id) as app_id, coalesce(c.day, m.day) as day,
       coalesce(c.llm_config_sk, m.llm_config_sk) as llm_config_sk, c.n as expected, m.n as in_mart
from checks c
full join marts m on m.mart = c.mart and m.app_id = c.app_id and m.day = c.day and m.llm_config_sk = c.llm_config_sk
where c.n is distinct from m.n
