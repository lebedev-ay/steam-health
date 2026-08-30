create or replace view marts.dim_game_current as
select
    game_sk, app_id, game_name, app_type,
    is_free, metacritic_score, release_date_parsed,
    collection_status
from core.dim_game
where is_current and app_id > 0;
