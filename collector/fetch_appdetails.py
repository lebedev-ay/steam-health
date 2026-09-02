import json
import time
import argparse

import requests
import psycopg

from db import DSN, read_games

URL = "https://store.steampowered.com/api/appdetails"


def fetch(app_id):
    response = requests.get(
        URL,
        params={"appids": app_id, "cc": "us", "l": "english"},
        headers={"User-Agent": "steam-health/0.1"},
        timeout=30,
    )
    return response.status_code, response.json() if response.ok else None


def save(app_id, status, payload):
    with psycopg.connect(DSN) as conn:
        conn.execute(
            "insert into raw.appdetails (app_id, http_status, payload) values (%s, %s, %s)",
            (app_id, status, json.dumps(payload) if payload else None),
        )
        conn.commit()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-id", type=int)
    return parser.parse_args()


def main():
    args = parse_args()
    for app_id, name in read_games(args.app_id):
        status, payload = fetch(app_id)
        save(app_id, status, payload)
        print(f"{name}: {status}")
        time.sleep(1.5)

if __name__ == "__main__":
    main()