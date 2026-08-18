create table core.fct_player_count (
    game_sk      int not null references core.dim_game(game_sk),
    date_sk      int not null references core.dim_date(date_sk),
    time_sk      smallint not null references core.dim_time(time_sk),
    measured_at  timestamptz not null,
    player_count int not null,
    is_on_sale   boolean,
    loaded_at    timestamptz not null default now(),
    primary key (game_sk, measured_at)
);

create index ix_fct_player_count_time
    on core.fct_player_count (game_sk, measured_at);