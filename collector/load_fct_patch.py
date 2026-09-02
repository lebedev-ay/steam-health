import argparse
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from classify_news import classify
from db import DSN, find_game_sk


def load_all(conn, app_id=None):
    app_filter = "and n.app_id = %s" if app_id is not None else ""
    params = (app_id,) if app_id is not None else ()

    rows = conn.execute(f"""
        select distinct on (item ->> 'gid')
            n.app_id,
            item ->> 'gid'      as gid,
            item ->> 'title'    as title,
            item ->> 'url'      as url,
            item ->> 'feedname' as feedname,
            (item ->> 'feed_type')::int as feed_type,
            length(item ->> 'contents') as body_length,
            to_timestamp((item ->> 'date')::bigint) as published_at
        from raw.news n,
             jsonb_array_elements(n.payload -> 'appnews' -> 'newsitems') as item
        where item ->> 'feedname' not in ('SteamDB')
        {app_filter}
        order by item ->> 'gid', n.fetched_at desc
    """, params).fetchall()

    inserted = 0
    for r in rows:
        if r["feed_type"] == 1:
            version, kind = classify(r["title"])
        else:
            version, kind = None, "press"

        game_sk = find_game_sk(conn, r["app_id"], r["published_at"])
        date_sk = int(r["published_at"].strftime("%Y%m%d"))

        conn.execute(
            """
            insert into core.fct_patch
                (gid, game_sk, date_sk, published_at, title, url,
                 feed_type, feedname, body_length, is_patch, event_type, version)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (gid) do update set
                game_sk = excluded.game_sk,
                date_sk = excluded.date_sk,
                published_at = excluded.published_at,
                title = excluded.title,
                url = excluded.url,
                feed_type = excluded.feed_type,
                feedname = excluded.feedname,
                is_patch = excluded.is_patch,
                event_type = excluded.event_type,
                version = excluded.version,
                body_length = excluded.body_length
            """,
            (r["gid"], game_sk, date_sk, r["published_at"], r["title"],
             r["url"], r["feed_type"], r["feedname"], r["body_length"],
             kind == "patch", kind, version),
        )
        inserted += 1

    weight_filter = "and g.app_id = %s" if app_id is not None else ""
    weight_params = (app_id,) if app_id is not None else ()

    conn.execute(f"""
        -- медиана по app_id, не по game_sk: game_sk — суррогат
        -- SCD2, у игры с несколькими версиями атрибутов (например,
        -- сменился metacritic-score) патчи разложены по разным
        -- game_sk, и медиана считалась бы отдельно для каждой
        -- версии — веса внутри одной игры переставали быть
        -- сравнимыми друг с другом
        with medians as (
            select g.app_id,
                   (percentile_cont(0.5)
                      within group (order by p.body_length))::numeric as med
            from core.fct_patch p
            join core.dim_game g on g.game_sk = p.game_sk
            where p.body_length > 0 and p.event_type = 'patch'
            group by g.app_id
        )
        update core.fct_patch p
        set weight = round(p.body_length::numeric / greatest(m.med, 1), 2)
        from core.dim_game g, medians m
        where g.game_sk = p.game_sk
          and g.app_id = m.app_id
          and p.body_length > 0
          {weight_filter}
    """, weight_params)

    return inserted


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-id", type=int)
    return parser.parse_args()


def main():
    args = parse_args()

    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        inserted = load_all(conn, args.app_id)
        conn.commit()

    print(f"загружено: {inserted}")
    print("витрины (marts) не пересобраны — запустите dbt run в dbt/")


if __name__ == "__main__":
    main()