import argparse
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from classify_news import classify
from db import DSN


def find_game_sk(conn, app_id, moment):
    row = conn.execute(
        """
        select game_sk from core.dim_game
        where app_id = %s and %s >= valid_from and %s < valid_to
        """,
        (app_id, moment, moment),
    ).fetchone()
    return row["game_sk"] if row else -1


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

    conn.execute("""
        with medians as (
            select game_sk,
                   (percentile_cont(0.5)
                      within group (order by body_length))::numeric as med
            from core.fct_patch
            where body_length > 0 and event_type = 'patch'
            group by game_sk
        )
        update core.fct_patch p
        set weight = round(p.body_length::numeric / greatest(m.med, 1), 2)
        from medians m
        where m.game_sk = p.game_sk and p.body_length > 0
    """)

    return inserted


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-id", type=int)
    return parser.parse_args()


def main():
    args = parse_args()

    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        inserted = load_all(conn, args.app_id)

        if args.app_id is not None:
            print("--app-id не сужает refresh: materialized view пересчитывается "
                  "целиком для всех игр (~7 минут)")

        conn.execute("refresh materialized view marts.patch_impact")

        conn.commit()

    print(f"загружено: {inserted}")


if __name__ == "__main__":
    main()