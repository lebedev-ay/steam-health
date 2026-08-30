-- refresh materialized view concurrently требует хотя бы один
-- unique-индекс без where на материализованном представлении.
-- Нужен для фоновой пересборки patch_impact (web/tasks.py):
-- полный refresh занимает ~7 минут, concurrently не блокирует
-- чтение на это время, ценой более медленной самой пересборки.
--
-- Уникальна пара (patch_sk, window_code): группировка в V23
-- включает patch_sk и window_code, на каждый патч — ровно
-- одна строка на каждое окно из dim_window (7 строк на патч).

create unique index ux_patch_impact_patch_window
    on marts.patch_impact (patch_sk, window_code);
