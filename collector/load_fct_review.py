import argparse
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from db import DSN

BATCH_SIZE = 20000


def watermarks(conn, app_id=None):
    # граница уже загруженного считается по самим фактам: у отдельной таблицы-счётчика был бы шанс разойтись с ними
    app_cond = "and g.app_id = %s" if app_id is not None else ""
    params = (app_id,) if app_id is not None else ()

    rows = conn.execute(f"""
        select g.app_id, max(f.loaded_from) as loaded_from
        from core.fct_review f
        join core.dim_game g on g.game_sk = f.game_sk
        where f.loaded_from is not null
          and g.app_id > 0
        {app_cond}
        group by g.app_id
    """, params).fetchall()

    return {r["app_id"]: r["loaded_from"] for r in rows}


def build_source(app_id, since, until, full, marks):
    """Присоединение и условие для отбора страниц raw плюс описание режима для вывода."""
    join, conds, params = "", [], []

    if full:
        mode = "полный, весь raw"
    elif since is not None or until is not None:
        bounds = []
        if since is not None:
            conds.append("r.fetched_at >= %s")
            params.append(since)
            bounds.append(f"fetched_at >= {since}")
        if until is not None:
            conds.append("r.fetched_at < %s")
            params.append(until)
            bounds.append(f"fetched_at < {until}")
        mode = "окно, " + " и ".join(bounds)
    elif marks:
        # знак у каждой игры свой: общий на всех пропустил бы игру, которая отстала со сбором, и её страницы не попали бы в ядро уже никогда.
        # Граница строгая - страницы с этим же fetched_at уже загружены, перечитывать их значит переписывать строки впустую
        values = ", ".join(["(%s::int, %s::timestamptz)"] * len(marks))
        join = f"left join (values {values}) as w (app_id, loaded_from) on w.app_id = r.app_id"
        for pair in sorted(marks.items()):
            params.extend(pair)
        conds.append("(w.loaded_from is null or r.fetched_at > w.loaded_from)")

        low, high = min(marks.values()), max(marks.values())
        edge = low if low == high else f"{low} .. {high}"
        mode = f"инкремент, fetched_at > {edge}"
    else:
        mode = "инкремент, загруженного ещё нет - читается весь raw"

    if app_id is not None:
        conds.append("r.app_id = %s")
        params.append(app_id)

    where = "where " + " and ".join(conds) if conds else ""
    return join, where, tuple(params), mode


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
    # review_sk для текстов берётся из returning основной вставки: искать его обратным соединением с core.fct_review значит читать всю таблицу фактов на каждой пачке
    cur = conn.execute("""
        with src as (
            select t.game_sk,
                   t.item,
                   t.fetched_at,
                   (t.item ->> 'recommendationid')::bigint                as recommendation_id,
                   to_timestamp((t.item ->> 'timestamp_created')::bigint) as created_at
            from tmp_review t
            where t.rn > %s and t.rn <= %s
        ),
        fact as (
            insert into core.fct_review (
                recommendation_id, game_sk, date_sk, time_sk, language_sk,
                author_steam_id, created_at, updated_at, dev_responded_at,
                is_voted_up, votes_up, votes_funny, comment_count, weighted_vote_score,
                playtime_at_review_min, playtime_forever_min, playtime_last_two_weeks_min,
                steam_purchase, received_for_free, written_during_early_access, loaded_from
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
                (s.item ->> 'written_during_early_access')::boolean,
                s.fetched_at
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
                is_voted_up = excluded.is_voted_up,
                loaded_from = excluded.loaded_from
            -- порция старше уже записанной не должна откатывать счётчики: backfill за прошлую дату приходит после свежего прогона и данными новее не располагает.
            -- Строку, не прошедшую условие, returning не отдаёт, поэтому её текст тоже остаётся нетронутым
            where core.fct_review.loaded_from is null
               or excluded.loaded_from >= core.fct_review.loaded_from
            returning review_sk, recommendation_id
        )
        insert into core.review_text (review_sk, review_body)
        select f.review_sk, s.item ->> 'review'
        from fact f
        join src s on s.recommendation_id = f.recommendation_id
        on conflict (review_sk) do update set review_body = excluded.review_body
    """, (first_rn, last_rn))

    return cur.rowcount


def load_all(conn, app_id=None, since=None, until=None, full=False):
    explicit = full or since is not None or until is not None
    marks = {} if explicit else watermarks(conn, app_id)
    join, where, params, mode = build_source(app_id, since, until, full, marks)
    print(f"режим: {mode}")

    # версия игры на момент отзыва ищется одним join. Задвоить строки могло бы только пересечение интервалов SCD2
    conn.execute(f"""
        create temporary table tmp_review as
        select row_number() over () as rn,
               coalesce(g.game_sk, -1) as game_sk,
               d.item,
               d.fetched_at
        from (
            select distinct on (item ->> 'recommendationid')
                r.app_id,
                item,
                r.fetched_at,
                to_timestamp((item ->> 'timestamp_created')::bigint) as created_at
            from raw.reviews r {join},
                 jsonb_array_elements(r.payload -> 'reviews') as item
            {where}
            order by item ->> 'recommendationid', r.fetched_at desc
        ) d
        left join core.dim_game g
               on g.app_id = d.app_id
              and d.created_at >= g.valid_from
              and d.created_at <  g.valid_to
    """, params)

    # без индекса каждая пачка читала бы временную таблицу целиком
    conn.execute("create index on tmp_review (rn)")
    conn.commit()

    total = conn.execute("select count(*) as n from tmp_review").fetchone()["n"]
    print(f"всего отзывов: {total}")

    if total == 0:
        print("нового нет")
        return 0

    load_languages(conn)

    loaded = 0
    first_rn = 0

    while first_rn < total:
        loaded += load_reviews(conn, first_rn, first_rn + BATCH_SIZE)
        conn.commit()
        first_rn += BATCH_SIZE
        print(f"{loaded}/{total}")

    return loaded


def moment(value):
    # без часового пояса значение читается как UTC: в этом поясе живёт и база, и fetched_at
    return datetime.fromisoformat(value)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-id", type=int)
    parser.add_argument("--since", type=moment, help="нижняя граница fetched_at, включительно")
    parser.add_argument("--until", type=moment, help="верхняя граница fetched_at, исключительно")
    parser.add_argument("--full", action="store_true", help="перечитать весь raw")
    args = parser.parse_args()

    if args.full and (args.since is not None or args.until is not None):
        parser.error("--full не сочетается с --since и --until")

    return args


def main():
    args = parse_args()
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        loaded = load_all(conn, args.app_id, args.since, args.until, args.full)

    print(f"загружено: {loaded}")


if __name__ == "__main__":
    main()
