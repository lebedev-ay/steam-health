-- marts.patch_impact, marts.review_flat и marts.dim_game_current
-- теперь строит dbt/ (см. decisions.md, запись 030) — определения
-- этих витрин здесь, в миграциях, были только до переезда, и с тех
-- пор дублируются в dbt/models/. Два владельца у одного объекта
-- работали только по случайности: миграции создавали витрину
-- одного типа, dbt run пересоздавал под тем же именем — уже
-- другого. Убираем миграции из этой цепочки: дальше core (эта
-- схема, db/migration/) заполняет только ядро, marts — целиком
-- зона dbt. На чистой базе после этой миграции схема marts пуста
-- до первого dbt run — это ожидаемо, не поломка.
--
-- core.dim_window не трогаем: это измерение, оно остаётся в ядре
-- и в миграциях, dbt только читает его через source().
--
-- тип объекта на момент удаления не гарантирован. На чистой базе,
-- где применялись только миграции, patch_impact — materialized
-- view (создан в V23), review_flat и dim_game_current — view. Но
-- если на этой же базе уже хоть раз прогонялся dbt run, оба уже
-- обычная table (materialized='table' в dbt/models/) — drop
-- с указанием не того вида объекта падает даже под if exists,
-- эта проверка только про "объекта нет вообще". Поэтому тип
-- смотрим динамически через pg_class.relkind и удаляем тем
-- способом, который этому типу подходит.
do $$
declare
    kind "char";
begin
    select c.relkind into kind
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'marts' and c.relname = 'patch_impact';

    if kind = 'm' then
        execute 'drop materialized view marts.patch_impact';
    elsif kind is not null then
        execute 'drop table marts.patch_impact';
    end if;

    select c.relkind into kind
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'marts' and c.relname = 'review_flat';

    if kind = 'v' then
        execute 'drop view marts.review_flat cascade';
    elsif kind is not null then
        execute 'drop table marts.review_flat cascade';
    end if;

    select c.relkind into kind
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'marts' and c.relname = 'dim_game_current';

    if kind = 'v' then
        execute 'drop view marts.dim_game_current';
    elsif kind is not null then
        execute 'drop table marts.dim_game_current';
    end if;
end $$;
