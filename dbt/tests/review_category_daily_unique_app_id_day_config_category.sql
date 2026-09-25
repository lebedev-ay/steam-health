select app_id, day, llm_config_sk, category_id, count(*) as n
from {{ ref('review_category_daily') }}
group by app_id, day, llm_config_sk, category_id
having count(*) > 1
