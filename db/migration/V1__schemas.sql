create schema if not exists raw;
create schema if not exists core;
create schema if not exists marts;

comment on schema raw is 'Сырые данные Steam API, append-only, без трансформаций';
comment on schema core is 'Измерения и факты, владелец — Flyway';
comment on schema marts is 'Витрины, владелец — dbt';