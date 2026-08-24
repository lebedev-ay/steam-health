import json
import time

import requests
import psycopg

from db import DSN, read_games

URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v0002/"


def fetch_page(app_id):
    response = requests.get(
        URL.format(app_id=app_id),
        params={
            "appid": app_id,
            "count": 500,
            "maxlength": 0,
        },
        headers={"User-Agent": "steam-health/0.1"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def collect(conn, app_id, name):

    try:
        data = fetch_page(app_id)
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


def main():

    games = read_games()
    grand_total = 0

    with psycopg.connect(DSN) as conn:
        for app_id, name in games:
            grand_total += collect(conn, app_id, name)
            time.sleep(1.5)
    
    print(f"\nвсего: {grand_total}")


if __name__ == "__main__":
    main()