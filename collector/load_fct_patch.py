import os
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

from classify_news import classify

load_dotenv()

DSN = (
    f"host=localhost port=5433 "
    f"dbname={os.getenv('POSTGRES_DB')} "
    f"user={os.getenv('POSTGRES_USER')} "
    f"password={os.getenv('POSTGRES_PASSWORD')}"
)


def find_game_sk(conn, app_id, moment):
    row = conn.execute(
        """
        select game_sk from core.dim_game
        where app_id = %s and %s >= valid_from and %s < valid_to
        """,
        (app_id, moment, moment),
    ).fetchone()
    return row["game_sk"] if row else -1


def main():
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        rows = conn.execute("""
            select distinct on (item ->> 'gid')
                n.app_id,
                item ->> 'gid'      as gid,
                item ->> 'title'    as title,
                item ->> 'url'      as url,
                item ->> 'feedname' as feedname,
                (item ->> 'feed_type')::int as feed_type,
                to_timestamp((item ->> 'date')::bigint) as published_at
            from raw.news n,
                 jsonb_array_elements(n.payload -> 'appnews' -> 'newsitems') as item
            where (item ->> 'feed_type')::int = 1
        """).fetchall()

        inserted = 0
        for r in rows:
            version, kind = classify(r["title"])
            game_sk = find_game_sk(conn, r["app_id"], r["published_at"])
            date_sk = int(r["published_at"].strftime("%Y%m%d"))

            conn.execute(
                """
                insert into core.fct_patch
                    (gid, game_sk, date_sk, published_at, title, url,
                     feed_type, feedname, is_patch, event_type, version)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (gid) do update set
                    game_sk = excluded.game_sk,
                    is_patch = excluded.is_patch,
                    event_type = excluded.event_type,
                    version = excluded.version
                """,
                (r["gid"], game_sk, date_sk, r["published_at"], r["title"],
                 r["url"], r["feed_type"], r["feedname"],
                 kind == "patch", kind, version),
            )
            inserted += 1

        conn.commit()

    print(f"загружено: {inserted}")


if __name__ == "__main__":
    main()