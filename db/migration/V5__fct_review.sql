create table core.dim_language (
    language_sk   serial primary key,
    language_code text not null unique,   -- 'english', 'russian', 'schinese'
    language_name text
);

insert into core.dim_language (language_sk, language_code, language_name)
values (-1, 'unknown', 'Unknown');

create table core.fct_review (
    review_sk         bigserial primary key,
    recommendation_id bigint not null unique,

    -- измерения
    game_sk           int not null references core.dim_game(game_sk),
    date_sk           int not null references core.dim_date(date_sk),
    time_sk           smallint not null references core.dim_time(time_sk),
    language_sk       int not null references core.dim_language(language_sk),

    -- degenerate dimension
    author_steam_id   bigint,

    -- вехи accumulating snapshot
    created_at        timestamptz not null,
    updated_at        timestamptz,
    dev_responded_at  timestamptz,

    -- меры
    is_voted_up       boolean not null,
    votes_up          int not null default 0,
    votes_funny       int not null default 0,
    comment_count     int not null default 0,
    weighted_vote_score numeric(10,8),

    playtime_at_review_min      int,
    playtime_forever_min        int,
    playtime_last_two_weeks_min int,

    -- флаги-контекст
    steam_purchase              boolean,
    received_for_free           boolean,
    written_during_early_access boolean,
    refunded                    boolean,

    loaded_at         timestamptz not null default now()
);

-- главный запрос: отзывы по игре за период
create index ix_fct_review_game_time
    on core.fct_review (game_sk, created_at);

create table core.review_text (
    review_sk   bigint primary key references core.fct_review(review_sk),
    review_body text
);