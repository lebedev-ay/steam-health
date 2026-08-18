create table raw.reviews (
    raw_id     bigserial primary key,
    app_id     int not null,
    cursor_in  text,
    fetched_at timestamptz not null default now(),
    payload    jsonb not null
);

create index ix_raw_reviews_app on raw.reviews (app_id, fetched_at);