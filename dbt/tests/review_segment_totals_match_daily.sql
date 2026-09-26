-- каждый разрез, кроме наигранных часов (у части отзывов их нет), покрывает все отзывы игры: сумма по сегментам равна сумме по дням
with daily as (
    select app_id, sum(review_count) as n from {{ ref('review_daily') }} group by app_id
),
segments as (
    select app_id, dimension, sum(review_count) as n
    from {{ ref('review_segment') }}
    where dimension <> 'playtime'
    group by app_id, dimension
)
select s.app_id, s.dimension, s.n as in_segments, d.n as in_daily
from segments s
join daily d on d.app_id = s.app_id
where s.n <> d.n
