select app_id, period_from, count(*) as n
from {{ ref('game_digest_current') }}
group by app_id, period_from
having count(*) > 1
