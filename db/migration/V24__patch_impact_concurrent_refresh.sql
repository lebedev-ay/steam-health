-- refresh materialized view concurrently требует хотя бы один unique-индекс без where: без него фоновая пересборка блокирует чтение витрины.
-- Пара (patch_sk, window_code) уникальна по построению из V23 - на каждый патч по строке на окно.

create unique index ux_patch_impact_patch_window
    on marts.patch_impact (patch_sk, window_code);
