import argparse

import psycopg
from psycopg.rows import dict_row

from db import DSN

BATCH_SIZE = 20000


def load_languages(conn):
    # коды языков заводятся разом по всему срезу: иначе на каждый отзыв уходил отдельный запрос.
    # Пустой код словарной строки не получает, в фактах ему отвечает -1
    conn.execute("""
        insert into core.dim_language (language_code)
        select distinct item ->> 'language'
        from tmp_review
        where nullif(item ->> 'language', '') is not null
        on conflict (language_code) do nothing
    """)


def load_reviews(conn, first_rn, last_rn):
    cur = conn.execute("""
        with src as (
            select t.game_sk,
                   t.item,
                   (t.item ->> 'recommendationid')::bigint                as recommendation_id,
                   to_timestamp((t.item ->> 'timestamp_created')::bigint) as created_at
            from tmp_review t
            where t.rn > %s and t.rn <= %s
        )
        insert into core.fct_review (
            recommendation_id, game_sk, date_sk, time_sk, language_sk,
            author_steam_id, created_at, updated_at, dev_responded_at,
            is_voted_up, votes_up, votes_funny, comment_count, weighted_vote_score,
            playtime_at_review_min, playtime_forever_min, playtime_last_two_weeks_min,
            steam_purchase, received_for_free, written_during_early_access
        )
        select
            s.recommendation_id,
            s.game_sk,
            to_char(s.created_at at time zone 'utc', 'YYYYMMDD')::int,
            extract(hour from s.created_at at time zone 'utc')::smallint,
            coalesce(l.language_sk, -1),
            nullif(s.item -> 'author' ->> 'steamid', '')::bigint,
            s.created_at,
            -- ноль у Steam значит "не было": ни обновления, ни ответа разработчика
            to_timestamp(nullif((s.item ->> 'timestamp_updated')::bigint, 0)),
            to_timestamp(nullif((s.item ->> 'timestamp_dev_responded')::bigint, 0)),
            (s.item ->> 'voted_up')::boolean,
            coalesce((s.item ->> 'votes_up')::int, 0),
            coalesce((s.item ->> 'votes_funny')::int, 0),
            coalesce((s.item ->> 'comment_count')::int, 0),
            (s.item ->> 'weighted_vote_score')::numeric,
            (s.item -> 'author' ->> 'playtime_at_review')::int,
            (s.item -> 'author' ->> 'playtime_forever')::int,
            (s.item -> 'author' ->> 'playtime_last_two_weeks')::int,
            (s.item ->> 'steam_purchase')::boolean,
            (s.item ->> 'received_for_free')::boolean,
            (s.item ->> 'written_during_early_access')::boolean
        from src s
        left join core.dim_language l
               on l.language_code = nullif(s.item ->> 'language', '')
        on conflict (recommendation_id) do update set
            votes_up = excluded.votes_up,
            votes_funny = excluded.votes_funny,
            comment_count = excluded.comment_count,
            weighted_vote_score = excluded.weighted_vote_score,
            updated_at = excluded.updated_at,
            dev_responded_at = excluded.dev_responded_at,
            is_voted_up = excluded.is_voted_up
    """, (first_rn, last_rn))

    # review_sk выдаёт последовательность, поэтому тексты идут вторым проходом - по уже вставленным фактам
    conn.execute("""
        insert into core.review_text (review_sk, review_body)
        select f.review_sk, t.item ->> 'review'
        from tmp_review t
        join core.fct_review f
          on f.recommendation_id = (t.item ->> 'recommendationid')::bigint
        where t.rn > %s and t.rn <= %s
        on conflict (review_sk) do update set review_body = excluded.review_body
    """, (first_rn, last_rn))

    return cur.rowcount


def load_all(conn, app_id=None):
    app_filter = "where r.app_id = %s" if app_id is not None else ""
    params = (app_id,) if app_id is not None else ()

    # версия игры на момент отзыва ищется одним join. Задвоить строки могло бы только пересечение интервалов SCD2
    conn.execute(f"""
        create temporary table tmp_review as
        select row_number() over () as rn,
               coalesce(g.game_sk, -1) as game_sk,
               d.item
        from (
            select distinct on (item ->> 'recommendationid')
                r.app_id,
                item,
                to_timestamp((item ->> 'timestamp_created')::bigint) as created_at
            from raw.reviews r,
                 jsonb_array_elements(r.payload -> 'reviews') as item
            {app_filter}
            order by item ->> 'recommendationid', r.fetched_at desc
        ) d
        left join core.dim_game g
               on g.app_id = d.app_id
              and d.created_at >= g.valid_from
              and d.created_at <  g.valid_to
    """, params)

    # без индекса каждая пачка читала бы временную таблицу целиком.
    # Статистика по ней намеренно не собирается: с ней планировщик берёт для текстов hash join по всей core.fct_review (1.6 с против 0.1 с на пачку)
    conn.execute("create index on tmp_review (rn)")
    conn.commit()

    total = conn.execute("select count(*) as n from tmp_review").fetchone()["n"]
    print(f"всего отзывов: {total}")

    load_languages(conn)

    loaded = 0
    first_rn = 0

    while first_rn < total:
        loaded += load_reviews(conn, first_rn, first_rn + BATCH_SIZE)
        conn.commit()
        first_rn += BATCH_SIZE
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
