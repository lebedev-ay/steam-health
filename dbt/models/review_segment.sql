{{ config(materialized='table') }}

-- Кто пишет отзывы: число отзывов и положительных в разрезах аудитории, одна строка на (app_id, dimension, segment).
-- Сегменты хранятся кодами, подписи к ним - на дашборде. sort_order - естественный порядок внутри разреза (часы по возрастанию)
with reviews as (
    select g.app_id,
           f.is_voted_up,
           f.playtime_at_review_min as minutes,
           l.language_code,
           f.received_for_free,
           f.steam_purchase,
           f.written_during_early_access,
           f.dev_responded_at is not null as dev_responded
    from {{ source('core', 'fct_review') }} f
    join {{ source('core', 'dim_game') }} g on g.game_sk = f.game_sk
    join {{ source('core', 'dim_language') }} l on l.language_sk = f.language_sk
    where g.app_id > 0
)
select r.app_id,
       s.dimension,
       s.segment,
       s.sort_order,
       count(*) as review_count,
       count(*) filter (where r.is_voted_up) as positive_count
from reviews r
cross join lateral (values
    -- 2 часа - граница возврата в Steam: до неё игрок ещё решает, оставлять ли игру
    ('playtime',
     case when r.minutes is null then null
          when r.minutes < 120 then 'h0_2'
          when r.minutes < 600 then 'h2_10'
          when r.minutes < 3000 then 'h10_50'
          when r.minutes < 12000 then 'h50_200'
          else 'h200' end,
     case when r.minutes is null then null
          when r.minutes < 120 then 1
          when r.minutes < 600 then 2
          when r.minutes < 3000 then 3
          when r.minutes < 12000 then 4
          else 5 end),
    ('language', r.language_code, 0),
    ('purchase',
     case when r.received_for_free then 'free' when r.steam_purchase then 'steam' else 'key' end,
     case when r.received_for_free then 3 when r.steam_purchase then 1 else 2 end),
    ('early_access', case when r.written_during_early_access then 'early_access' else 'release' end,
     case when r.written_during_early_access then 1 else 2 end),
    ('dev_response', case when r.dev_responded then 'answered' else 'silent' end,
     case when r.dev_responded then 1 else 2 end)
) as s (dimension, segment, sort_order)
where s.segment is not null
group by r.app_id, s.dimension, s.segment, s.sort_order
