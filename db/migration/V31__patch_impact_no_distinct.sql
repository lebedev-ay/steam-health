-- distinct в reviews было нужно, пока review_flat разворачивала
-- raw.reviews с дублями (запись 017). После V21 review_flat читает
-- core.fct_review, где recommendation_id уникален — дедупликация
-- уже произошла на загрузке, тут distinct лишний: пересортировывал
-- под миллион строк на каждый refresh просто так.
--
-- Всё остальное — колонки, окна, bounds, window_complete,
-- группировка — как в V23, без изменений.

drop materialized view marts.patch_impact;

create materialized view marts.patch_impact as
with reviews as (
    select app_id, review_id, created_at, voted_up
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

-- нужен для refresh concurrently (web/tasks.py), см. V24
create unique index ux_patch_impact_patch_window
    on marts.patch_impact (patch_sk, window_code);
