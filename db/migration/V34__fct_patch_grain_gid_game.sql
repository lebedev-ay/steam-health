-- Зерно fct_patch - пара «событие - игра», а не одно событие: новость
-- Steam может относиться к нескольким играм, и у каждой она свой факт
-- со своим весом. Ключ по одному gid держал такую заметку единственной
-- строкой, а game_sk доставался от последнего прогона. Цена нового
-- зерна - дубли строк у 53 событий из 13360. Существующие строки
-- не пересоздаются, недостающие допишет load_fct_patch.py.
alter table core.fct_patch drop constraint fct_patch_gid_key;

alter table core.fct_patch
    add constraint ux_fct_patch_gid_game unique (gid, game_sk);
