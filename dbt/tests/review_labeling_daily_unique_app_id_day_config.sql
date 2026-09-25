select app_id, day, llm_config_sk, count(*) as n
from {{ ref('review_labeling_daily') }}
group by app_id, day, llm_config_sk
having count(*) > 1
