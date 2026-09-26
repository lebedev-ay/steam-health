select app_id, dimension, segment, count(*) as n
from {{ ref('review_segment') }}
group by app_id, dimension, segment
having count(*) > 1
