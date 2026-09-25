-- LLM-разметка отзывов аспектами со знаком: справочник, конфигурация разметчика, заголовок разметки отзыва и теги.
-- Решения и цифры исследования - docs/llm/exploration.md.

-- Справочник аспектов по версиям. Строки заводит llm/codebook.py из файла справочника, версия после заморозки не меняется
create table core.dim_aspect (
    aspect_sk           serial primary key,
    codebook_version    text not null,          -- 'v5'
    aspect_id           text not null,          -- 'pricing_fairness'; служебный 'other' - тема вне справочника
    aspect_name         text not null,
    aspect_definition   text not null,
    category_id         text not null,
    category_name       text not null,
    category_definition text not null,
    loaded_at           timestamptz not null default now(),
    constraint ux_dim_aspect unique (codebook_version, aspect_id)
);

-- Конфигурация разметчика. Версия промпта - хэш итогового текста: правка шаблона или справочника даёт новую строку сама, номер руками не ведётся
create table core.dim_llm_config (
    llm_config_sk    serial primary key,
    model            text not null,             -- 'qwen/qwen3.8-flash'
    prompt_name      text not null,             -- имя шаблона, 'closed-v2'
    codebook_version text not null,
    system_prompt    text not null,             -- итоговый текст, как ушёл в модель
    prompt_hash      text not null,             -- sha256(system_prompt)
    created_at       timestamptz not null default now(),
    constraint ux_dim_llm_config unique (prompt_hash, model)
);

-- Заголовок: одна версия текста, одна конфигурация. Уникальность пары - идемпотентность прогона
create table core.fct_review_labeling (
    labeling_sk    bigserial primary key,
    review_text_sk bigint not null references core.review_text_version(review_text_sk),
    llm_config_sk  int not null references core.dim_llm_config(llm_config_sk),
    status         text not null check (status in ('labeled', 'no_opinion', 'too_short', 'failed')),
    run_id         text not null,
    labeled_at     timestamptz not null default now(),
    day_rank       int,                         -- номер в дневной выборке игры; у too_short не заполняется
    constraint ux_fct_review_labeling unique (review_text_sk, llm_config_sk)
);

create index ix_fct_review_labeling_config on core.fct_review_labeling (llm_config_sk, status);

-- Теги разметки. Естественный ключ - заголовок + порядок важности
create table core.fct_review_aspect (
    labeling_sk bigint not null references core.fct_review_labeling(labeling_sk) on delete cascade,
    importance  smallint not null check (importance between 1 and 5),   -- 1 - главный аспект отзыва
    aspect_sk   int not null references core.dim_aspect(aspect_sk),
    sentiment   text not null check (sentiment in ('+', '-', '±')),
    note        text,                                                   -- метка темы у other, 1-3 слова
    primary key (labeling_sk, importance)
);

-- Один аспект не повторяется в отзыве, несколько other с разными метками допустимы
create unique index ux_fct_review_aspect_once
    on core.fct_review_aspect (labeling_sk, aspect_sk, coalesce(note, ''));

create index ix_fct_review_aspect_aspect on core.fct_review_aspect (aspect_sk);

comment on column core.fct_review_labeling.status is
    'labeled - есть теги; no_opinion - модель вернула пустой список (мемы, отзывы без мнения); '
    'too_short - короче порога, в модель не отправлялся; failed - ответ не прошёл проверку и после поштучного повтора, следующий прогон повторит';
