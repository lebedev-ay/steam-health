import json
import time
import argparse

import requests
import psycopg

from db import DSN, read_games

URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v0002/"


def fetch_page(app_id, enddate=None):
    params = {
        "appid": app_id,
        "count": 500,
        "maxlength": 0,
    }
    if enddate is not None:
        params["enddate"] = enddate

    response = requests.get(
        URL.format(app_id=app_id),
        params=params,
        headers={"User-Agent": "steam-health/0.1"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def latest_published_at(conn, app_id):
    row = conn.execute(
        """
        select max(p.published_at)
        from core.fct_patch p
        join core.dim_game g on g.game_sk = p.game_sk
        where g.app_id = %s
        """,
        (app_id,),
    ).fetchone()
    return row[0] if row else None


def collect(conn, app_id, name, mode):
    enddate = None
    if mode == "incremental":
        # новости неизменяемы и имеют gid, поэтому можно просто
        # попросить у API только то, что не новее последнего
        # известного события. Если событий по игре ещё нет —
        # ведём себя как full.
        latest = latest_published_at(conn, app_id)
        if latest is not None:
            enddate = int(latest.timestamp())

    try:
        data = fetch_page(app_id, enddate)
    except Exception as e:
        print(f"  ошибка: {e}")
        return 0

    news = (data.get("appnews") or {}).get("newsitems") or []

    conn.execute(
        "insert into raw.news (app_id, payload) values (%s, %s)",
        (app_id, json.dumps(data)),
    )
    conn.commit()

    total = len(news)

    print(f"{name}: {total}")
    return total


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-id", type=int)
    parser.add_argument("--mode", choices=["incremental", "full"], default="incremental")
    return parser.parse_args()


def main():
    args = parse_args()

    games = read_games(args.app_id)
    grand_total = 0

    with psycopg.connect(DSN) as conn:
        for app_id, name in games:
            grand_total += collect(conn, app_id, name, args.mode)
            time.sleep(1.5)

    print(f"\nвсего: {grand_total}")


if __name__ == "__main__":
    main()