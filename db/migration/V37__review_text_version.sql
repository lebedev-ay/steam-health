-- Версии текстов отзывов, попавших в LLM-разметку. core.review_text хранит только последний текст и перезаписывает его на месте, а разметка привязана к конкретному тексту: правка отзыва после разметки даёт новую версию, а не подменяет размеченное.
-- Естественный ключ версии - recommendation_id + md5 текста. Строки заводит llm/texts.py при разметке, из core.review_text через core.fct_review; версии есть только у отзывов, отобранных в разметку или отсечённых как too_short.
create table core.review_text_version (
    review_text_sk    bigserial primary key,
    recommendation_id bigint not null,
    text_hash         text not null,            -- md5(review_body)
    review_body       text not null,
    language_sk       int not null references core.dim_language(language_sk),
    valid_from        timestamptz not null,     -- updated_at отзыва на момент снятия версии, без правок - created_at
    is_current        boolean not null,
    loaded_at         timestamptz not null default now(),
    constraint ux_review_text_version unique (recommendation_id, text_hash)
);

-- У отзыва не может быть двух текущих текстов
create unique index ux_review_text_version_current
    on core.review_text_version (recommendation_id) where is_current;

comment on table core.review_text_version is
    'Версии текстов отзывов для LLM-разметки, снимаются из core.review_text в момент разметки. '
    'Текущая - версия, совпавшая с core.review_text при последнем прогоне разметки по этому отзыву. '
    'Отзывы вне разметки здесь не хранятся.';
