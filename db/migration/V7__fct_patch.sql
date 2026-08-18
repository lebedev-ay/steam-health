create table core.fct_patch (
    patch_sk     bigserial primary key,
    gid          text not null unique,      -- натуральный ключ новости
    game_sk      int not null references core.dim_game(game_sk),
    date_sk      int not null references core.dim_date(date_sk),
    published_at timestamptz not null,
    title        text,
    url          text,
    feed_type    smallint,
    feedname     text,
    is_patch     boolean not null default false,
    loaded_at    timestamptz not null default now()
);

create index ix_fct_patch_game_time
    on core.fct_patch (game_sk, published_at);

-- для lateral join по патчам
create index ix_fct_patch_is_patch
    on core.fct_patch (game_sk, published_at) where is_patch;