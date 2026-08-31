create table core.dim_platform_event (
    event_sk   serial primary key,
    gid        text not null unique,     -- натуральный ключ новости appid 753
    event_date date not null,
    event_type text not null check (event_type in ('sale', 'awards', 'fest', 'other')),
    title      text,
    url        text,
    source     text,                     -- feedname источника, обычно PCGamesN
    loaded_at  timestamptz not null default now()
);

create index ix_dim_platform_event_date on core.dim_platform_event (event_date);

comment on table core.dim_platform_event is
    'События платформы Steam (распродажи, Steam Awards, Next Fest), '
    'собираются из фида внешней прессы appid 753 (fetch_platform_events.py). '
    'event_date — дата публикации заметки, а не начала события: '
    'заметка выходит в день события или на день позже, окно поиска '
    'рядом с переломом (±3 дня) эту погрешность покрывает.';
