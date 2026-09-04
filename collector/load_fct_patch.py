import argparse

import psycopg
from psycopg.rows import dict_row

from classify_news import classify
from db import DSN
from fetch_platform_events import PLATFORM_APP_ID


def load_all(conn, app_id=None):
    app_filter = "and n.app_id = %s" if app_id is not None else ""
    params = (PLATFORM_APP_ID, app_id) if app_id is not None else (PLATFORM_APP_ID,)

    # зерно - пара «событие - игра»: одну заметку про несколько игр
    # берём по разу на каждую (см. миграцию V34).
    # Версия ищется одним join; задвоить события могло бы только
    # пересечение интервалов SCD2, запрещённое ограничением из V30
    rows = conn.execute(f"""
        select d.*, coalesce(g.game_sk, -1) as game_sk
        from (
            select distinct on (item ->> 'gid', n.app_id)
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
              -- фид платформы живёт в core.dim_platform_event, игры для
              -- него в dim_game нет - в fct_patch он давал только заглушки
              and n.app_id <> %s
            {app_filter}
            order by item ->> 'gid', n.app_id, n.fetched_at desc
        ) d
        left join core.dim_game g
               on g.app_id = d.app_id
              and d.published_at >= g.valid_from
              and d.published_at <  g.valid_to
    """, params).fetchall()

    inserted = 0
    for r in rows:
        if r["feed_type"] == 1:
            version, kind = classify(r["title"])
        else:
            version, kind = None, "press"

        date_sk = int(r["published_at"].strftime("%Y%m%d"))

        conn.execute(
            """
            insert into core.fct_patch
                (gid, game_sk, date_sk, published_at, title, url,
                 feed_type, feedname, body_length, is_patch, event_type, version)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (gid, game_sk) do update set
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
            (r["gid"], r["game_sk"], date_sk, r["published_at"], r["title"],
             r["url"], r["feed_type"], r["feedname"], r["body_length"],
             kind == "patch", kind, version),
        )
        inserted += 1

    weight_filter = "and g.app_id = %s" if app_id is not None else ""
    weight_params = (app_id,) if app_id is not None else ()

    # вес снимается перед пересчётом и в более широкой области, чем сам
    # пересчёт: медиана могла исчезнуть вместе с последним патчем игры,
    # и тогда update до такой игры не доходит, а старое число остаётся
    conn.execute(f"""
        update core.fct_patch p
        set weight = null
        from core.dim_game g
        where g.game_sk = p.game_sk
          and p.weight is not null
          {weight_filter}
    """, weight_params)

    conn.execute(f"""
        -- медиана по app_id, а не по game_sk: иначе у игры
        -- с несколькими версиями SCD2 веса внутри одной игры
        -- переставали быть сравнимыми - decisions.md, запись 027
        with patch_medians as (
            select g.app_id,
                   (percentile_cont(0.5)
                      within group (order by p.body_length))::numeric as med
            from core.fct_patch p
            join core.dim_game g on g.game_sk = p.game_sk
            where p.body_length > 0 and p.event_type = 'patch'
            group by g.app_id
        ),
        -- запасная база на случай, когда классификатор не распознал
        -- у игры ни одного патча: без неё шкала веса обнуляется целиком.
        -- Заглушка Unknown сюда не идёт - это не игра
        all_medians as (
            select g.app_id,
                   (percentile_cont(0.5)
                      within group (order by p.body_length))::numeric as med
            from core.fct_patch p
            join core.dim_game g on g.game_sk = p.game_sk
            where p.body_length > 0 and g.app_id > 0
            group by g.app_id
        ),
        -- базы не смешиваются: есть хоть один патч - медиана только
        -- по патчам, иначе веса внутри игры перестанут быть сравнимыми
        medians as (
            select a.app_id, coalesce(pm.med, a.med) as med
            from all_medians a
            left join patch_medians pm on pm.app_id = a.app_id
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
    print("витрины (marts) не пересобраны - запустите dbt run в dbt/")


if __name__ == "__main__":
    main()