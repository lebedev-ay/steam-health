-- Витрина окон marts.patch_impact удалена вместе с таблицей влияния
-- событий: график с переломами отвечает на тот же вопрос, других
-- потребителей у неё не было, а список событий дашборд читает прямо
-- из core.fct_patch. Модель убрана из dbt/models/, но объект в базе
-- от этого не исчезает - отсюда миграция. Про выбор способа удаления
-- по pg_class.relkind - см. V32.
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
