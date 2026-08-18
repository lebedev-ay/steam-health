create table raw.appdetails (
    raw_id      bigserial primary key,
    app_id      int not null,
    fetched_at  timestamptz not null default now(),
    http_status int,
    payload     jsonb
);

create index ix_raw_appdetails_app on raw.appdetails (app_id, fetched_at);