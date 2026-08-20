import os
import sys
import json
import time
from pathlib import Path

import requests
import psycopg
from dotenv import load_dotenv

load_dotenv()

DSN = (
    f"host=localhost port=5433 "
    f"dbname={os.getenv('POSTGRES_DB')} "
    f"user={os.getenv('POSTGRES_USER')} "
    f"password={os.getenv('POSTGRES_PASSWORD')}"
)

URL = "https://store.steampowered.com/appreviews/{app_id}"
GAMES = Path(__file__).parent / "games.txt"


def fetch_page(app_id, cursor):
    response = requests.get(
        URL.format(app_id=app_id),
        params={
            "json": 1,
            "filter": "recent",
            "language": "all",
            "purchase_type": "all",
            "num_per_page": 100,
            "cursor": cursor,
        },
        headers={"User-Agent": "steam-health/0.1"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def read_games():
    games = []
    for line in GAMES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        app_id, name = line.split(maxsplit=1)
        games.append((int(app_id), name))
    return games


def collect(conn, app_id, name, max_pages):
    cursor = "*"
    total = 0

    for page in range(max_pages):
        try:
            data = fetch_page(app_id, cursor)
        except Exception as e:
            print(f"  ошибка на странице {page + 1}: {e}")
            break

        reviews = data.get("reviews") or []
        if not reviews:
            break

        conn.execute(
            "insert into raw.reviews (app_id, cursor_in, payload) values (%s, %s, %s)",
            (app_id, cursor, json.dumps(data)),
        )
        conn.commit()

        total += len(reviews)

        next_cursor = data.get("cursor")
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor

        time.sleep(1.5)

    print(f"{name}: {total}")
    return total


def main():
    max_pages = int(sys.argv[1]) if len(sys.argv) > 1 else 30

    games = read_games()
    grand_total = 0

    with psycopg.connect(DSN) as conn:
        for app_id, name in games:
            grand_total += collect(conn, app_id, name, max_pages)

    print(f"\nвсего: {grand_total}")


if __name__ == "__main__":
    main()