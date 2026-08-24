-- Витрины переключаются с raw.reviews на core.fct_review: демо-дамп
-- пойдёт без raw, плюс не нужно разворачивать JSON на каждый запрос.
-- Колонки и типы review_flat не меняются, поэтому create or replace
-- не ломает marts.patch_impact, построенный поверх неё.

create or replace view marts.review_flat as
select
    g.app_id,
    r.recommendation_id as review_id,
    r.created_at,
    r.is_voted_up        as voted_up,
    l.language_code,
    r.created_at::date   as created_date
from core.fct_review r
join core.dim_game g on g.game_sk = r.game_sk
join core.dim_language l on l.language_sk = r.language_sk;
