create table raw.news (
    raw_id     bigserial primary key,
    app_id     int not null,
    fetched_at timestamptz not null default now(),
    payload    jsonb not null
);

create index ix_raw_news_app on raw.news (app_id, fetched_at);