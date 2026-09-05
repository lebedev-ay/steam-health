-- patch_impact из представления становится материализованным: cross join событий с окнами и вложенный цикл по датам пересчитывались на каждый клик в дашборде.
-- Определение взято из V20 без изменений, меняется только вид объекта. review_flat остаётся представлением - после V21 он не разворачивает JSON, и пересчёт у него дешёвый.

drop view if exists marts.patch_impact;

create materialized view marts.patch_impact as
with reviews as (
    select distinct app_id, review_id, created_at, voted_up
    from marts.review_flat
),
bounds as (
    select app_id, min(created_at) as data_from, max(created_at) as data_to
    from marts.review_flat
    group by app_id
),
patches as (
    select
        p.patch_sk, p.gid, p.title, p.version, p.event_type,
        p.published_at, p.body_length, p.weight,
        g.app_id, g.game_name
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
    p.body_length,
    p.weight,
    p.published_at,
    p.published_at::date as published_date,
    w.window_code,
    w.day_from,
    w.day_to,
    w.is_baseline,
    count(rv.review_id)                            as review_count,
    count(rv.review_id) filter (where rv.voted_up) as positive_count,
    (p.published_at + (w.day_from || ' days')::interval >= b.data_from
     and p.published_at + (w.day_to || ' days')::interval <= b.data_to) as window_complete
from patches p
cross join core.dim_window w
join bounds b on b.app_id = p.app_id
left join reviews rv
       on rv.app_id = p.app_id
      and rv.created_at >= p.published_at + (w.day_from || ' days')::interval
      and rv.created_at <  p.published_at + (w.day_to   || ' days')::interval
group by p.patch_sk, p.app_id, p.game_name, p.title, p.version,
         p.event_type, p.body_length, p.weight, p.published_at,
         w.window_code, w.day_from, w.day_to, w.is_baseline,
         b.data_from, b.data_to
with data;

-- основной путь доступа из web/app.py: app_id + window_code = 'after_7'
create index ix_patch_impact_app_window
    on marts.patch_impact (app_id, window_code);
