import os
import sys
import json

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

URL = "https://store.steampowered.com/api/appdetails"


def fetch(app_id: int):
    response = requests.get(
        URL,
        params={"appids": app_id, "cc": "us", "l": "english"},
        timeout=30,
    )
    return response.status_code, response.json() if response.ok else None


def save(app_id: int, status: int, payload):
    with psycopg.connect(DSN) as conn:
        conn.execute(
            "insert into raw.appdetails (app_id, http_status, payload) values (%s, %s, %s)",
            (app_id, status, json.dumps(payload) if payload else None),
        )
        conn.commit()


from pathlib import Path

GAMES = Path(__file__).parent / "games.txt"

def read_games():
    games = []
    for line in GAMES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        app_id, name = line.split(maxsplit=1)
        games.append((int(app_id), name))
    return games


def main():
    import time
    for app_id, name in read_games():
        status, payload = fetch(app_id)
        save(app_id, status, payload)
        print(f"{name}: {status}")
        time.sleep(1.5)

if __name__ == "__main__":
    main()