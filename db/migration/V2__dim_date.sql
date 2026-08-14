create table core.dim_date (
    date_sk      int primary key,           -- 20260812
    full_date    date not null unique,
    year         smallint not null,
    quarter      smallint not null,
    month        smallint not null,
    month_name   text not null,
    day          smallint not null,
    day_of_week  smallint not null,         -- 1=понедельник, 7=воскресенье
    day_name     text not null,
    week_of_year smallint not null,
    is_weekend   boolean not null,
    is_holiday   boolean not null default false
);

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
from generate_series('2012-01-01'::date, '2030-12-31'::date, '1 day') as d;