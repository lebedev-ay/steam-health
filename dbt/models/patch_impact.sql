{{ config(
    materialized='table',
    indexes=[
      {'columns': ['app_id', 'window_code']},
      {'columns': ['patch_sk', 'window_code'], 'unique': True}
    ]
) }}

-- границы собранных данных по каждой игре: за их пределами
-- окно неполное, сравнивать нельзя (см. decisions.md, запись 009)
with bounds as (
    select
        app_id,
        min(day) as data_from,
        max(day) as data_to
    from {{ ref('review_daily') }}
    group by app_id
),

patches as (
    select
        p.patch_sk,
        p.gid,
        p.title,
        p.version,
        p.event_type,
        p.published_at,
        p.body_length,
        p.weight,
        g.app_id,
        g.game_name
    from {{ source('core', 'fct_patch') }} p
    join {{ source('core', 'dim_game') }} g on g.game_sk = p.game_sk
),

-- каждая пара «событие + окно» разворачивается в список календарных
-- дат этого окна. Дальше отзывы подставляются по равенству дат,
-- а не диапазонным сравнением: раньше база строила 2.1 млрд пар
-- «отзыв × окно» и выбрасывала 99.5% фильтром после соединения
expanded as (
    select
        p.patch_sk,
        p.app_id,
        w.window_code,
        d::date as day
    from patches p
    cross join {{ source('core', 'dim_window') }} w
    cross join lateral generate_series(
        (p.published_at::date + (case when w.day_from >= 0 then w.day_from + 1 else w.day_from end))::timestamp,
        (p.published_at::date + (case when w.day_to   >  0 then w.day_to        else -1        end))::timestamp,
        interval '1 day'
    ) as d
),

counted as (
    select
        e.patch_sk,
        e.window_code,
        coalesce(sum(rd.review_count), 0)   as review_count,
        coalesce(sum(rd.positive_count), 0) as positive_count
    from expanded e
    left join {{ ref('review_daily') }} rd
        on rd.app_id = e.app_id
       and rd.day    = e.day
    group by e.patch_sk, e.window_code
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
    c.review_count,
    c.positive_count,
    p.published_at::date + w.day_from >= b.data_from
        and p.published_at::date + w.day_to <= b.data_to
        as window_complete
from patches p
cross join {{ source('core', 'dim_window') }} w
join bounds b on b.app_id = p.app_id
join counted c on c.patch_sk = p.patch_sk and c.window_code = w.window_code