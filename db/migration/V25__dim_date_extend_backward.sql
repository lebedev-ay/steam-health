-- V2 заполнила dim_date диапазоном 2012-01-01..2030-12-31. У части игр (например, Terraria) есть новости раньше - вставка в fct_patch падает по внешнему ключу, date_sk не находит строку в измерении.
-- Steam запущен в сентябре 2003, более старых данных быть не может.
--
-- Таблица не пересоздаётся: недостающие строки за 2003-2011 добавляются insert-ом, той же логикой вычисления полей, что в V2.

insert into core.dim_date
select
    to_char(d, 'YYYYMMDD')::int,
    d::date,
    extract(year from d),
    extract(quarter from d),
    extract(month from d),
    to_char(d, 'TMMonth'),
    extract(day from d),
    extract(isodow from d),
    to_char(d, 'TMDay'),
    extract(week from d),
    extract(isodow from d) in (6, 7),
    false
from generate_series('2003-01-01'::date, '2011-12-31'::date, '1 day') as d;
