-- LLM-разметка новостей игры (llm/news.py): масштаб события для игры, его вид, анонс это или уже случилось, короткое русское название.
-- Масштаб по заголовку и длине патчноута не определить: релиз 1.0 бывает коротким постом, а сотня мелких исправлений - длинным.
-- Строка - одна новость одной конфигурацией по одному тексту: gid + хэш текста. Текст правили - новая строка, прежняя остаётся.
-- Ключ - gid, а не пара с игрой: масштаб - свойство самой новости, а новость одна и та же у всех игр, к которым относится.
create table core.fct_news_label (
    news_label_sk  bigserial primary key,
    gid            text not null,
    text_hash      text not null,                 -- md5 заголовка и текста, как их видела модель
    llm_config_sk  int not null references core.dim_llm_config(llm_config_sk),
    status         text not null check (status in ('labeled', 'failed')),
    tier           text check (tier in ('milestone', 'major', 'regular', 'background')),
    kind           text check (kind in ('release', 'expansion', 'major_update', 'season', 'content_update', 'balance',
                                        'hotfix', 'event', 'roadmap', 'announcement', 'sale', 'community', 'other')),
    is_future      boolean,                        -- анонс будущего, а не случившееся: дата выхода, «скоро», предзаказ
    title_ru       text,                           -- короткое русское название для подписи на графике, до 40 символов
    run_id         text not null,
    labeled_at     timestamptz not null default now(),
    constraint ux_fct_news_label unique (gid, text_hash, llm_config_sk),
    -- у размеченной строки поля заполнены, у упавшей - пусты: частичная разметка хуже никакой
    constraint ck_fct_news_label_filled check (
        (status = 'labeled') = (tier is not null and kind is not null and is_future is not null and title_ru is not null))
);

comment on table core.fct_news_label is
    'LLM-разметка новостей игры: уровень (milestone - веха, major - крупное, regular - обычное, background - фон), вид, анонс, '
    'русское название. Текущая по активной конфигурации - marts.news_label_current';
