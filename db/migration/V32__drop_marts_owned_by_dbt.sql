-- Витрины marts переехали в dbt (decisions.md, запись 030), и файл
-- снимает их с миграций: дальше db/migration/ отвечает за ядро,
-- marts целиком за dbt. На чистой базе схема marts пуста до первого
-- dbt run.
--
-- Вид объекта на момент удаления не гарантирован: там, где применялись
-- только миграции, patch_impact - materialized view, а после первого
-- dbt run - обычная table. Drop с указанием не того вида падает даже
-- под if exists, эта проверка гасит только «объекта нет вообще».
-- Поэтому вид читается из pg_class.relkind и по нему выбирается
-- способ удаления.
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
