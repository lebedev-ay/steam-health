-- Сводка месяца по игре (llm/digest.py): заголовок и 2-3 фразы, написанные моделью по числам витрин разметки.
-- Модель видит только агрегаты - доли тем, оценки, новости и переломы, без текстов отзывов: вызов стоит порядка тысячи токенов.
-- Строка - одна сводка одной конфигурацией генерации по одному набору улик; улики не изменились - сводка не пересчитывается.
create table core.fct_game_digest (
    digest_sk            bigserial primary key,
    app_id               int not null,
    period_from          date not null,                -- первый день месяца
    period_to            date not null,                -- первый день следующего месяца, не входит
    llm_config_sk        int not null references core.dim_llm_config(llm_config_sk),   -- генерация: промпт сводки, модель, параметры
    labeling_config_sk   int not null references core.dim_llm_config(llm_config_sk),   -- разметка, по которой собраны улики
    evidence             jsonb not null,
    evidence_hash        text not null,
    headline             text not null,
    summary              text not null,
    checks               jsonb not null default '[]',  -- замечания проверок кодом; пусто - проверки пройдены
    checks_passed        boolean not null,
    attempts             smallint not null default 1,
    run_id               text not null,
    created_at           timestamptz not null default now(),
    input_tokens         int not null default 0,
    cached_tokens        int not null default 0,
    output_tokens        int not null default 0,
    reasoning_tokens     int not null default 0,
    cost_usd             numeric(12, 6),
    constraint ux_fct_game_digest unique (app_id, period_from, llm_config_sk, evidence_hash)
);

create index ix_fct_game_digest_period on core.fct_game_digest (app_id, period_from, created_at desc);
