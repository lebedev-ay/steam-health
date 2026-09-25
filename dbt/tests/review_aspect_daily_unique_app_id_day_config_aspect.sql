select app_id, day, llm_config_sk, aspect_id, count(*) as n
from {{ ref('review_aspect_daily') }}
group by app_id, day, llm_config_sk, aspect_id
having count(*) > 1
