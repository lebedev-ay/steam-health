-- Какие игры размечаются и получают выводы по расписанию (llm.label и llm.verdict с --all-enabled).
-- Не колонка dim_game: это настройка работы, а не свойство игры, и новая версия игры в SCD2 не должна её копировать или сбрасывать.
-- Ключ - app_id: версии игры тут ни при чём, а внешнего ключа на dim_game нет - app_id там не уникален.
create table core.llm_game (
    app_id      int primary key,
    enabled     boolean not null,
    enabled_at  timestamptz not null default now(),   -- с какого момента настройка в нынешнем состоянии: включена или выключена
    note        text
);

comment on table core.llm_game is
    'Игры для LLM-разметки и выводов по расписанию. Выключенная игра остаётся строкой с enabled = false: '
    'по ней видно, что разметка была и когда её остановили. Ручной запуск python -m llm.label --app-id на эту настройку не смотрит';

-- пилот: на этих двух играх проверялись разметка, всплески и выводы
insert into core.llm_game (app_id, enabled, note) values
    (892970, true, 'пилот: Valheim'),
    (2344520, true, 'пилот: Diablo IV')
on conflict (app_id) do nothing;
