import json
import re

import requests
import psycopg
from psycopg.rows import dict_row

from db import DSN

URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v0002/"
PLATFORM_APP_ID = 753  # служебный appid Steam, не игра

# сезон/праздник + sale, "steam" встречается в обоих порядках.
# Голый "steam sale" не ловим: под него попадают издательские
# распродажи вида "Capcom Steam sale" - промо, не событие платформы
SALE_RE = re.compile(
    r'\b(summer|winter|spring|autumn|fall|holiday|black\s+friday|'
    r'halloween|lunar new year|chinese new year|christmas)'
    r'\s+(?:steam\s+)?sale\b',
    re.IGNORECASE,
)

# "game of the year" отдельно не проверяем: слишком много чужих
# премий, а у Steam Awards он всегда идёт вместе с "steam awards"
AWARDS_RE = re.compile(r'\bsteam\s+awards\b', re.IGNORECASE)

# next fest - частный случай \w+\s+fest\b. Сюда же попадают
# Replayability и Digital Tabletop Fest, тоже платформенные
FEST_RE = re.compile(r'\b\w+\s+fest\b', re.IGNORECASE)


def classify_event(title):
    if AWARDS_RE.search(title):
        return "awards"
    if SALE_RE.search(title):
        return "sale"
    if FEST_RE.search(title):
        return "fest"
    return None  # железо, суды, Гейб Ньюэлл и т.д. - не наше


def fetch_page():
    response = requests.get(
        URL,
        params={"appid": PLATFORM_APP_ID, "count": 500, "maxlength": 0},
        headers={"User-Agent": "steam-health/0.1"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def fetch(conn):
    # один вызов с count=500 покрывает весь фид с 2014 года:
    # постраничный обход назад по времени здесь не нужен
    data = fetch_page()
    news = (data.get("appnews") or {}).get("newsitems") or []

    conn.execute(
        "insert into raw.news (app_id, payload) values (%s, %s)",
        (PLATFORM_APP_ID, json.dumps(data)),
    )
    conn.commit()

    print(f"appid 753: скачано {len(news)}")
    return len(news)


def load_all(conn):
    rows = conn.execute("""
        select distinct on (item ->> 'gid')
            item ->> 'gid'      as gid,
            item ->> 'title'    as title,
            item ->> 'url'      as url,
            item ->> 'feedname' as source,
            to_timestamp((item ->> 'date')::bigint)::date as event_date
        from raw.news n,
             jsonb_array_elements(n.payload -> 'appnews' -> 'newsitems') as item
        where n.app_id = %s
          and (item ->> 'feed_type')::int = 0
        order by item ->> 'gid', n.fetched_at desc
    """, (PLATFORM_APP_ID,)).fetchall()

    inserted = 0
    for r in rows:
        event_type = classify_event(r["title"])
        if event_type is None:
            continue

        conn.execute("""
            insert into core.dim_platform_event
                (gid, event_date, event_type, title, url, source)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (gid) do update set
                event_date = excluded.event_date,
                event_type = excluded.event_type,
                title      = excluded.title,
                url        = excluded.url,
                source     = excluded.source
        """, (r["gid"], r["event_date"], event_type,
              r["title"], r["url"], r["source"]))
        inserted += 1

    conn.commit()
    return inserted


def main():
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        fetch(conn)
        inserted = load_all(conn)

    print(f"платформенных событий: {inserted}")


if __name__ == "__main__":
    main()
