select app_id, change_date, count(*) as n
from {{ ref('change_point_verdict_current') }}
group by app_id, change_date
having count(*) > 1
