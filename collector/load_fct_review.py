import argparse
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from db import DSN, find_game_sk

BATCH_SIZE = 1000


def find_language_sk(conn, language_code):
    if not language_code:
        return -1

    conn.execute(
        """
        insert into core.dim_language (language_code)
        values (%s)
        on conflict (language_code) do nothing
        """,
        (language_code,),
    )
    row = conn.execute(
        "select language_sk from core.dim_language where language_code = %s",
        (language_code,),
    ).fetchone()
    return row["language_sk"]


def load_review(conn, app_id, item, language_cache):
    author = item.get("author") or {}

    created_at = datetime.fromtimestamp(int(item["timestamp_created"]), tz=timezone.utc)

    updated_ts = item.get("timestamp_updated")
    updated_at = datetime.fromtimestamp(int(updated_ts), tz=timezone.utc) if updated_ts else None

    dev_ts = item.get("timestamp_dev_responded")
    dev_responded_at = datetime.fromtimestamp(int(dev_ts), tz=timezone.utc) if dev_ts else None

    game_sk = find_game_sk(conn, app_id, created_at)

    language_code = item.get("language")
    if language_code not in language_cache:
        language_cache[language_code] = find_language_sk(conn, language_code)
    language_sk = language_cache[language_code]

    date_sk = int(created_at.strftime("%Y%m%d"))
    time_sk = created_at.hour

    steamid = author.get("steamid")

    row = conn.execute(
        """
        insert into core.fct_review (
            recommendation_id, game_sk, date_sk, time_sk, language_sk,
            author_steam_id, created_at, updated_at, dev_responded_at,
            is_voted_up, votes_up, votes_funny, comment_count, weighted_vote_score,
            playtime_at_review_min, playtime_forever_min, playtime_last_two_weeks_min,
            steam_purchase, received_for_free, written_during_early_access
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (recommendation_id) do update set
            votes_up = excluded.votes_up,
            votes_funny = excluded.votes_funny,
            comment_count = excluded.comment_count,
            weighted_vote_score = excluded.weighted_vote_score,
            updated_at = excluded.updated_at,
            dev_responded_at = excluded.dev_responded_at,
            is_voted_up = excluded.is_voted_up
        returning review_sk
        """,
        (
            int(item["recommendationid"]), game_sk, date_sk, time_sk, language_sk,
            int(steamid) if steamid else None, created_at, updated_at, dev_responded_at,
            item["voted_up"], item.get("votes_up", 0), item.get("votes_funny", 0),
            item.get("comment_count", 0), item.get("weighted_vote_score"),
            author.get("playtime_at_review"), author.get("playtime_forever"),
            author.get("playtime_last_two_weeks"),
            item.get("steam_purchase"), item.get("received_for_free"),
            item.get("written_during_early_access"),
        ),
    ).fetchone()

    review_sk = row["review_sk"]

    conn.execute(
        """
        insert into core.review_text (review_sk, review_body)
        values (%s, %s)
        on conflict (review_sk) do update set review_body = excluded.review_body
        """,
        (review_sk, item.get("review")),
    )


def load_all(conn, app_id=None):
    app_filter = "where r.app_id = %s" if app_id is not None else ""
    params = (app_id,) if app_id is not None else ()

    conn.execute("drop table if exists tmp_review")
    conn.execute(f"""
        create temporary table tmp_review as
        select row_number() over () as rn, app_id, item
        from (
            select distinct on (item ->> 'recommendationid')
                r.app_id, item
            from raw.reviews r,
                 jsonb_array_elements(r.payload -> 'reviews') as item
            {app_filter}
            order by item ->> 'recommendationid', r.fetched_at desc
        ) d
    """, params)
    conn.commit()

    total = conn.execute("select count(*) as n from tmp_review").fetchone()["n"]
    print(f"всего отзывов: {total}")

    language_cache = {}
    loaded = 0
    last_rn = 0

    while True:
        rows = conn.execute(
            """
            select rn, app_id, item from tmp_review
            where rn > %s
            order by rn
            limit %s
            """,
            (last_rn, BATCH_SIZE),
        ).fetchall()

        if not rows:
            break

        for r in rows:
            load_review(conn, r["app_id"], r["item"], language_cache)
            last_rn = r["rn"]

        conn.commit()
        loaded += len(rows)
        print(f"{loaded}/{total}")

    return loaded


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-id", type=int)
    return parser.parse_args()


def main():
    args = parse_args()
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        loaded = load_all(conn, args.app_id)

    print(f"загружено: {loaded}")


if __name__ == "__main__":
    main()
