import json
import time
import argparse

import requests
import psycopg

from db import DSN, read_games

URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v0002/"
REQUEST_PAUSE = 1.5
RETRY_PAUSES = (2, 4, 8)


def fetch_page(app_id, enddate=None):
    params = {
        "appid": app_id,
        "count": 500,
        "maxlength": 0,
    }
    if enddate is not None:
        params["enddate"] = enddate

    response = requests.get(
        URL,
        params=params,
        headers={"User-Agent": "steam-health/0.1"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def known_gids(conn, app_id, gids):
    # известность gid проверяем по raw.news, а не по core.fct_patch:
    # загрузчик (load_fct_patch.py) отбрасывает записи с feedname
    # 'SteamDB', их gid в fct_patch никогда не попадают и всегда
    # выглядели бы "неизвестными" — ранняя остановка не срабатывала
    # бы вообще. В raw.news лежит всё, что когда-либо скачали
    if not gids:
        return set()
    rows = conn.execute("""
        select distinct item ->> 'gid' as gid
        from raw.news n,
             jsonb_array_elements(n.payload -> 'appnews' -> 'newsitems') as item
        where n.app_id = %s and item ->> 'gid' = any(%s)
    """, (app_id, list(gids))).fetchall()
    return {r[0] for r in rows}


def collect(conn, app_id, name, max_pages, mode):
    # enddate у Steam — курсор "раньше этой даты", не фильтр "новее".
    # Листаем от свежих страниц к старым: на каждом шаге просим
    # то, что раньше минимальной даты уже увиденной страницы
    enddate = None
    prev_min_date = None
    total = 0

    for page in range(max_pages):
        data = None
        for attempt in range(len(RETRY_PAUSES) + 1):
            try:
                data = fetch_page(app_id, enddate)
                break
            except requests.RequestException as e:
                print(f"  ошибка на странице {page + 1}, попытка {attempt + 1}: {e}")
                if attempt < len(RETRY_PAUSES):
                    time.sleep(RETRY_PAUSES[attempt])

        if data is None:
            return total, False

        news = (data.get("appnews") or {}).get("newsitems") or []
        if not news:
            break

        page_min_date = min(item["date"] for item in news)

        # защита от зацикливания: просили строго раньше prev_min_date,
        # а получили не раньше — Steam вернул то же самое или новее
        if prev_min_date is not None and page_min_date >= prev_min_date:
            break

        gids = [item["gid"] for item in news]
        known = known_gids(conn, app_id, gids)

        if len(known) < len(gids):
            # хотя бы один gid новый — страницу стоит сохранить
            conn.execute(
                "insert into raw.news (app_id, payload) values (%s, %s)",
                (app_id, json.dumps(data)),
            )
            conn.commit()
            total += len(news)
        elif mode == "incremental":
            # всё уже известно, дальше будет только старее —
            # инкремент своё дело сделал. Full идёт до конца
            # независимо от известности
            break

        prev_min_date = page_min_date
        enddate = page_min_date - 1

        time.sleep(REQUEST_PAUSE)

    print(f"{name}: {total}")
    return total, True


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("max_pages", type=int, nargs="?", default=10)
    parser.add_argument("--app-id", type=int)
    parser.add_argument("--mode", choices=["incremental", "full"], default="incremental")
    return parser.parse_args()


def main():
    args = parse_args()

    games = read_games(args.app_id)
    grand_total = 0
    incomplete = []

    with psycopg.connect(DSN) as conn:
        for app_id, name in games:
            total, completed = collect(conn, app_id, name, args.max_pages, args.mode)
            grand_total += total
            if not completed:
                incomplete.append(name)

    print(f"\nвсего: {grand_total}")

    if incomplete:
        print(f"не докачано: {', '.join(incomplete)}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()