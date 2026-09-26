{{ config(materialized='view') }}

-- Текущая версия каждой игры с разработчиками, издателями и жанрами одной строкой - для шапки дашборда
select g.game_sk,
       g.app_id,
       g.game_name,
       g.app_type,
       g.is_free,
       g.metacritic_score,
       g.release_date_parsed,
       g.collection_status,
       (select string_agg(c.company_name, ', ' order by c.company_name)
        from {{ source('core', 'bridge_game_company') }} b
        join {{ source('core', 'dim_company') }} c on c.company_sk = b.company_sk
        where b.game_sk = g.game_sk and b.role = 'developer') as developers,
       (select string_agg(c.company_name, ', ' order by c.company_name)
        from {{ source('core', 'bridge_game_company') }} b
        join {{ source('core', 'dim_company') }} c on c.company_sk = b.company_sk
        where b.game_sk = g.game_sk and b.role = 'publisher') as publishers,
       (select string_agg(n.genre_name, ', ' order by n.genre_name)
        from {{ source('core', 'bridge_game_genre') }} b
        join {{ source('core', 'dim_genre') }} n on n.genre_sk = b.genre_sk
        where b.game_sk = g.game_sk) as genres
from {{ source('core', 'dim_game') }} g
where g.is_current
  and g.app_id > 0
