-- Витрина окон marts.patch_impact удалена вместе с таблицей влияния
-- событий на дашборде: график с переломами отвечает на тот же вопрос,
-- а других потребителей у витрины не было. Список событий для графика
-- теперь читается напрямую из core.fct_patch, меры окон (review_count,
-- positive_count, window_complete) не читает никто.
--
-- Модель удалена из dbt/models/, но объект в базе от этого не исчезает:
-- dbt дропает только то, что пересоздаёт. Отсюда эта миграция.
--
-- core.dim_window остаётся в ядре: это измерение, а не витрина, и V32
-- уже зафиксировала его как часть core. Сейчас его не читает никто.
--
-- Тип объекта на момент удаления не гарантирован, как и в V32: на базе,
-- где применялись только миграции, patch_impact - materialized view
-- из V31, а после первого dbt run - обычная table (materialized='table').
-- Указание не того вида объекта роняет drop даже под if exists: эта
-- проверка гасит только "объекта нет вообще". Поэтому вид смотрим
-- через pg_class.relkind и удаляем подходящим способом.
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
end $$;
