-- Точечная правка в psql (запись 006) переписала valid_from
-- на 2000-01-01 не только у первой версии игры, но и у более поздних,
-- и интервалы [valid_from, valid_to) внутри одного app_id стали
-- пересекаться. Файл восстанавливает границы, перепривязывает факты
-- по фактическому моменту и запрещает пересечения на будущее.
-- Разбор - decisions.md, запись 025.
with ordered as (
    select game_sk, app_id,
           lag(valid_to) over (partition by app_id order by valid_to, game_sk) as prev_valid_to
    from core.dim_game
    where app_id > 0
)
update core.dim_game g
set valid_from = o.prev_valid_to
from ordered o
where g.game_sk = o.game_sk
  and o.prev_valid_to is not null;

update core.fct_patch p
set game_sk = g.game_sk
from core.dim_game g
where p.game_sk <> -1
  and g.app_id = (select app_id from core.dim_game where game_sk = p.game_sk)
  and p.published_at >= g.valid_from
  and p.published_at < g.valid_to
  and g.game_sk <> p.game_sk;

update core.fct_review r
set game_sk = g.game_sk
from core.dim_game g
where r.game_sk <> -1
  and g.app_id = (select app_id from core.dim_game where game_sk = r.game_sk)
  and r.created_at >= g.valid_from
  and r.created_at < g.valid_to
  and g.game_sk <> r.game_sk;

-- для диапазонов нужен gist: обычный unique пересечения не ловит
create extension if not exists btree_gist;

alter table core.dim_game
    add constraint dim_game_no_overlap
    exclude using gist (
        app_id with =,
        tstzrange(valid_from, valid_to, '[)') with &&
    )
    where (app_id > 0);
