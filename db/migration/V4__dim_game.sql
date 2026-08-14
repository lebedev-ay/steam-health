-- Справочники-измерения

create table core.dim_company (
    company_sk   serial primary key,
    company_name text not null unique
);

create table core.dim_genre (
    genre_sk   int primary key,        -- id от Steam
    genre_name text not null
);

create table core.dim_category (
    category_sk   int primary key,     -- id от Steam
    category_name text not null
);

-- Измерение игры, SCD Type 2

create table core.dim_game (
    game_sk             serial primary key,
    app_id              int not null,              -- натуральный ключ, НЕ unique
    game_name           text not null,
    app_type            text,                      -- game / dlc / demo
    is_free             boolean,
    required_age        smallint,
    metacritic_score    smallint,
    metacritic_url      text,
    is_coming_soon      boolean not null default false,
    release_date_raw    text,
    release_date_parsed date,
    valid_from          timestamptz not null,
    valid_to            timestamptz not null default '9999-12-31 23:59:59+00',
    is_current          boolean not null default true,
    loaded_at           timestamptz not null default now()
);

-- У игры не может быть двух текущих версий одновременно
create unique index ux_dim_game_current
    on core.dim_game (app_id) where is_current;

-- Поиск версии на момент времени
create index ix_dim_game_lookup
    on core.dim_game (app_id, valid_from, valid_to);

-- Мосты

create table core.bridge_game_company (
    game_sk    int not null references core.dim_game(game_sk),
    company_sk int not null references core.dim_company(company_sk),
    role       text not null check (role in ('developer', 'publisher')),
    primary key (game_sk, company_sk, role)
);

create table core.bridge_game_genre (
    game_sk  int not null references core.dim_game(game_sk),
    genre_sk int not null references core.dim_genre(genre_sk),
    primary key (game_sk, genre_sk)
);

create table core.bridge_game_category (
    game_sk     int not null references core.dim_game(game_sk),
    category_sk int not null references core.dim_category(category_sk),
    primary key (game_sk, category_sk)
);

-- Строка "неизвестно" для фактов без опознанной игры
insert into core.dim_game
    (game_sk, app_id, game_name, valid_from, valid_to, is_current)
values
    (-1, -1, 'Unknown', '1970-01-01+00', '9999-12-31 23:59:59+00', true);