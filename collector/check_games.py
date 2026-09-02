import time

import requests

from db import read_games

URL = "https://store.steampowered.com/api/appdetails"


def main():
    for app_id, expected in read_games():
        r = requests.get(
            URL,
            params={"appids": app_id, "filters": "basic", "cc": "us", "l": "english"},
            timeout=30,
        )
        body = r.json().get(str(app_id), {})

        if not body.get("success"):
            print(f"{app_id:>9}  ОШИБКА — не найдено (ожидалось: {expected})")
        else:
            actual = body["data"].get("name", "?")
            mark = "ok  " if expected.lower() in actual.lower() else "МИМО"
            print(f"{app_id:>9}  {mark}  {actual}")

        time.sleep(1.5)


if __name__ == "__main__":
    main()