-- Выводы по точкам перелома: короткий текст по уликам из разметки (llm/verdict.py). Строка - один вывод одной конфигурацией генерации по одному набору улик.
-- Игра хранится как app_id, а не game_sk: вывод относится к игре на отрезке в две недели, а не к её версии SCD2, и так же адресуются витрины.
create table core.fct_change_point_verdict (
    verdict_sk           bigserial primary key,
    app_id               int not null,
    change_date          date not null,                -- день перелома; окно «до» - [before_from, change_date), «после» - [change_date, after_to)
    before_from          date not null,
    after_to             date not null,
    llm_config_sk        int not null references core.dim_llm_config(llm_config_sk),   -- генерация: промпт вывода, модель, параметры
    labeling_config_sk   int not null references core.dim_llm_config(llm_config_sk),   -- разметка, по которой собраны улики
    evidence             jsonb not null,               -- улики целиком, как их видела модель, с номерами отзывов-опор
    evidence_hash        text not null,                -- sha256 канонического JSON улик: не изменились - вывод не пересчитывается
    detector_shift_pp    numeric(6, 1),                -- сдвиг доли позитива по детектору дашборда; в хэш не входит, зависит от всего ряда
    author               text not null check (author in ('model', 'template')),        -- template - изменение незначимо, текст пишет код
    what_happened        text not null,
    what_players_say     text,                         -- у шаблона пусто
    support_numbers      int[] not null default '{}',  -- номера отзывов-опор из evidence, на которые ссылается what_players_say
    excerpts             jsonb not null default '[]',  -- 2-3 отрывка для дашборда: текст до 150 символов, votes_up, номер опоры
    checks               jsonb not null default '[]',  -- замечания проверок кодом; пусто - проверки пройдены
    checks_passed        boolean not null,
    attempts             smallint not null default 1,  -- 2 - первый ответ не прошёл проверки и был повтор
    status               text not null check (status in ('preliminary', 'final')),
    run_id               text not null,
    created_at           timestamptz not null default now(),
    input_tokens         int not null default 0,
    cached_tokens        int not null default 0,
    output_tokens        int not null default 0,
    reasoning_tokens     int not null default 0,
    cost_usd             numeric(12, 6),               -- null - цена неизвестна (не заданы цены модели)
    constraint ux_fct_change_point_verdict unique (app_id, change_date, llm_config_sk, evidence_hash)
);

create index ix_fct_change_point_verdict_point on core.fct_change_point_verdict (app_id, change_date, created_at desc);

comment on column core.fct_change_point_verdict.status is
    'preliminary - вывод сделан, пока окно «после» не закрыто с запасом на поздние отзывы (change_date + 7 + 3 дня); '
    'final - сделан или подтверждён после. Улики не изменились - предварительный вывод переводится в итоговый без генерации';
