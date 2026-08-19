create or replace view marts.review_flat as
select
    r.app_id,
    (review ->> 'recommendationid')::bigint            as review_id,
    to_timestamp((review ->> 'timestamp_created')::bigint) as created_at,
    (review ->> 'voted_up')::boolean                   as voted_up,
    review ->> 'language'                              as language_code
from raw.reviews r,
     jsonb_array_elements(r.payload -> 'reviews') as review;

create or replace view marts.patch_impact as
with reviews as (
    select distinct app_id, review_id, created_at, voted_up
    from marts.review_flat
),
patches as (
    select
        p.patch_sk, p.gid, p.title, p.version, p.event_type,
        p.published_at, g.app_id, g.game_name
    from core.fct_patch p
    join core.dim_game g on g.game_sk = p.game_sk
)
select
    p.patch_sk,
    p.app_id,
    p.game_name,
    p.title,
    p.version,
    p.event_type,
    p.published_at,
    w.window_code,
    w.day_from,
    w.day_to,
    w.is_baseline,
    count(rv.review_id)                                   as review_count,
    count(rv.review_id) filter (where rv.voted_up)        as positive_count
from patches p
cross join core.dim_window w
left join reviews rv
       on rv.app_id = p.app_id
      and rv.created_at >= p.published_at + (w.day_from || ' days')::interval
      and rv.created_at <  p.published_at + (w.day_to   || ' days')::interval
group by p.patch_sk, p.app_id, p.game_name, p.title, p.version,
         p.event_type, p.published_at,
         w.window_code, w.day_from, w.day_to, w.is_baseline;