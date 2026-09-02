import json
import time
import argparse

import psycopg

import steam_api
from db import DSN, read_games

URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v0002/"
REQUEST_PAUSE = 1.5


def fetch_page(app_id, enddate=None):
    params = {
        "appid": app_id,
        "count": 500,
        "maxlength": 0,
    }
    if enddate is not None:
        params["enddate"] = enddate

    return steam_api.get(URL, params)


def known_gids(conn, app_id, gids):
    # по raw.news, а не по core.fct_patch: загрузчик отбрасывает
    # SteamDB, и его gid всегда выглядели бы неизвестными
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
    # enddate у Steam - курсор "раньше этой даты", не фильтр "новее"
    # (см. decisions.md, запись 024): листаем от свежих к старым
    enddate = None
    prev_min_date = None
    total = 0

    for page in range(max_pages):
        data = fetch_page(app_id, enddate)
        if data is None:
            return total, False

        news = (data.get("appnews") or {}).get("newsitems") or []
        if not news:
            break

        page_min_date = min(item["date"] for item in news)

        # защита от зацикливания: просили строго раньше prev_min_date,
        # а получили не раньше - Steam вернул то же самое или новее
        if prev_min_date is not None and page_min_date >= prev_min_date:
            break

        gids = [item["gid"] for item in news]
        known = known_gids(conn, app_id, gids)

        if len(known) < len(gids):
            # хотя бы один gid новый - страницу стоит сохранить
            conn.execute(
                "insert into raw.news (app_id, payload) values (%s, %s)",
                (app_id, json.dumps(data)),
            )
            conn.commit()
            total += len(news)
        elif mode == "incremental":
            # всё уже известно, дальше будет только старее -
            # инкремент своё дело сделал, full идёт до конца
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