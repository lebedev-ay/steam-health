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
    if not isinstance(payload, dict) or not payload:
        # чаще всего это лимит запросов: Steam отвечает пустым телом или null
        print(f"  appdetails {app_id}: пустой или нечитаемый ответ")
        return {}

    items = {key: info if isinstance(info, dict) else {} for key, info in payload.items()}
    keys = [str(key)[:16] for key in items]

    for info in items.values():
        if info.get("success") and str(_steam_appid(info)) == str(app_id):
            return info

    if str(app_id) in items:
        info = items[str(app_id)]
    elif len(items) == 1:
        (key, info), = items.items()
        # чужой steam_appid - это карточка другой игры, брать нельзя
        if _steam_appid(info) is not None and str(_steam_appid(info)) != str(app_id):
            print(f"  appdetails {app_id}: нет подходящего элемента, ключи {keys}, steam_appid {_steam_appid(info)}")
            return {}
        if info.get("success"):
            print(f"  appdetails {app_id}: пришёл под ключом {key[:16]} без steam_appid")
    else:
        print(f"  appdetails {app_id}: нет подходящего элемента, ключи {keys}")
        return {}

    if not info.get("success"):
        print(f"  appdetails {app_id}: success={info.get('success')}, ключи {keys}")
    elif not info.get("data"):
        print(f"  appdetails {app_id}: success true без данных, ключи {keys}")
    return info


def _steam_appid(info):
    data = info.get("data")
    return data.get("steam_appid") if isinstance(data, dict) else None


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