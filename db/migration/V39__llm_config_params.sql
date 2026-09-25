-- Параметры генерации входят в конфигурацию разметчика: тот же промпт с другим размером пачки или temperature размечает иначе, и такую разметку нельзя смешивать с прежней.
-- Колонка без значения по умолчанию: строки, заведённые до неё, параметров не знают, и миграция на них падает, а не выдумывает параметры.
alter table core.dim_llm_config add column params jsonb not null;

alter table core.dim_llm_config drop constraint ux_dim_llm_config;
alter table core.dim_llm_config
    add constraint ux_dim_llm_config unique (prompt_hash, model, params);

comment on column core.dim_llm_config.params is
    'Параметры генерации: temperature, batch_size, max_tokens, reasoning. Часть естественного ключа конфигурации';

-- Короткие отзывы в базу не пишутся, их число считается на лету по длине текста: ни заголовка too_short, ни версии текста у них нет
alter table core.fct_review_labeling drop constraint fct_review_labeling_status_check;
alter table core.fct_review_labeling
    add constraint fct_review_labeling_status_check check (status in ('labeled', 'no_opinion', 'failed'));

comment on column core.fct_review_labeling.status is
    'labeled - есть теги; no_opinion - модель вернула пустой список (мемы, отзывы без мнения); '
    'failed - ответ не прошёл проверку и после поштучного повтора, следующий прогон повторит';

comment on column core.fct_review_labeling.day_rank is
    'Номер отзыва в дневной выборке игры, порядок по md5(recommendation_id). '
    'Ранг считается при каждом прогоне заново: если за уже размеченный день дособраны отзывы, размеченных в этом дне может стать больше лимита';

comment on table core.review_text_version is
    'Версии текстов отзывов для LLM-разметки, снимаются из core.review_text в момент разметки. '
    'Текущая - версия, совпавшая с core.review_text при последнем прогоне разметки по этому отзыву. '
    'Версии есть только у отзывов, отобранных в разметку; короткие отзывы и отзывы вне разметки здесь не хранятся.';
