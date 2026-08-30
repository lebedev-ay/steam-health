alter table core.dim_game add column collection_status text
    check (collection_status in ('complete', 'partial'));

comment on column core.dim_game.collection_status is
    'complete — все шаги collect_game прошли; partial — упал на '
    'каком-то шаге, данные в core за эту игру неполные; NULL — '
    'игра добавлена до появления этой колонки';
