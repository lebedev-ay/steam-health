import time
from pathlib import Path

import requests

GAMES = Path(__file__).parent / "games.txt"
URL = "https://store.steampowered.com/api/appdetails"


def main():
    for line in GAMES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        app_id, expected = line.split(maxsplit=1)

        r = requests.get(
            URL,
            params={"appids": app_id, "filters": "basic", "cc": "us", "l": "english"},
            timeout=30,
        )
        body = r.json().get(app_id, {})

        if not body.get("success"):
            print(f"{app_id:>9}  ОШИБКА — не найдено (ожидалось: {expected})")
        else:
            actual = body["data"].get("name", "?")
            mark = "ok  " if expected.lower() in actual.lower() else "МИМО"
            print(f"{app_id:>9}  {mark}  {actual}")

        time.sleep(1.5)


if __name__ == "__main__":
    main()