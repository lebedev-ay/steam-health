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


def pick(payload, app_id):
    """Элемент ответа по app_id. Steam бывает кладёт его под чужим ключом (2344520 -> "3958800"), свой id лежит в data.steam_appid."""
    items = payload or {}
    for info in items.values():
        info = info or {}
        if info.get("success") and str((info.get("data") or {}).get("steam_appid")) == str(app_id):
            return info
    if str(app_id) in items:
        return items[str(app_id)] or {}
    if len(items) == 1:
        (key, info), = items.items()
        info = info or {}
        if info.get("success"):
            print(f"  appdetails: app_id {app_id} пришёл под ключом {key}")
        return info
    return {}


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