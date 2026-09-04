import json
import time
import argparse

import psycopg

import steam_api
from db import DSN, read_games

URL = "https://store.steampowered.com/api/appdetails"
REQUEST_PAUSE = 1.5


def fetch(app_id):
    payload, status = steam_api.get_with_status(
        URL, {"appids": app_id, "cc": "us", "l": "english"})
    return status, payload


def save(conn, app_id, status, payload):
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
    with psycopg.connect(DSN) as conn:
        for app_id, name in read_games(args.app_id):
            status, payload = fetch(app_id)
            save(conn, app_id, status, payload)
            print(f"{name}: {status}")
            time.sleep(REQUEST_PAUSE)

if __name__ == "__main__":
    main()