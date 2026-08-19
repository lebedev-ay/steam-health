create table core.dim_window (
    window_sk    serial primary key,
    window_code  text not null unique,
    day_from     int not null,     -- относительно патча, включительно
    day_to       int not null,     -- исключительно
    is_baseline  boolean not null default false
);

insert into core.dim_window (window_code, day_from, day_to, is_baseline) values
    ('before_28', -28, 0, true),
    ('before_14', -14, 0, true),
    ('before_7',   -7, 0, true),
    ('after_1',     0,  1, false),
    ('after_3',     0,  3, false),
    ('after_7',     0,  7, false),
    ('after_14',    0, 14, false);