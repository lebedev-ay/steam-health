alter table core.fct_patch add column body_length int;
alter table core.fct_patch add column weight numeric(4,2);

comment on column core.fct_patch.body_length is 'Длина текста новости в символах';
comment on column core.fct_patch.weight is 'Отношение длины к медиане по игре: крупность релиза';