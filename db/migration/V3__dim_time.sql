create table core.dim_time (
    time_sk    smallint primary key,        -- 0..23
    hour_label text not null,               -- '14:00'
    daypart    text not null,               -- night/morning/day/evening
    is_peak    boolean not null
);

insert into core.dim_time
select
    h,
    lpad(h::text, 2, '0') || ':00',
    case
        when h between 0 and 5   then 'night'
        when h between 6 and 11  then 'morning'
        when h between 12 and 17 then 'day'
        else 'evening'
    end,
    h between 17 and 23
from generate_series(0, 23) as h;