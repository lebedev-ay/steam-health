import json
import time
import argparse

import requests
import psycopg

from db import DSN, read_games

URL = "https://store.steampowered.com/appreviews/{app_id}"
REQUEST_PAUSE = 1.5
RETRY_PAUSES = (2, 4, 8)


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


def known_recommendation_ids(conn, ids):
    if not ids:
        return set()
    rows = conn.execute(
        "select recommendation_id from core.fct_review where recommendation_id = any(%s)",
        (list(ids),),
    ).fetchall()
    return {r[0] for r in rows}


def collect(conn, app_id, name, max_pages, mode, on_page=None):
    cursor = "*"
    total = 0

    for page in range(max_pages):
        data = None
        for attempt in range(len(RETRY_PAUSES) + 1):
            try:
                data = fetch_page(app_id, cursor)
                break
            except requests.RequestException as e:
                print(f"  ошибка на странице {page + 1}, попытка {attempt + 1}: {e}")
                if attempt < len(RETRY_PAUSES):
                    time.sleep(RETRY_PAUSES[attempt])

        if data is None:
            return total, False

        reviews = data.get("reviews") or []
        if not reviews:
            break

        if mode == "incremental":
            # filter=recent сортирует по дате СОЗДАНИЯ отзыва. Если
            # вся страница уже есть в core.fct_review — дальше пойдут
            # только более старые уже известные отзывы, можно
            # останавливаться. Но так инкремент не увидит отзывы,
            # отредактированные после создания (например, автор
            # перевернул оценку через год) — они остаются на старой
            # позиции выдачи и не попадут в свежую страницу. Для
            # полной пересборки с нуля нужен режим full.
            batch_ids = [int(r["recommendationid"]) for r in reviews]
            known = known_recommendation_ids(conn, batch_ids)
            if len(known) == len(batch_ids):
                break

        conn.execute(
            "insert into raw.reviews (app_id, cursor_in, payload) values (%s, %s, %s)",
            (app_id, cursor, json.dumps(data)),
        )
        conn.commit()

        total += len(reviews)

        if on_page:
            on_page(page + 1, total)

        next_cursor = data.get("cursor")
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor

        time.sleep(REQUEST_PAUSE)

    print(f"{name}: {total}")
    return total, True


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("max_pages", type=int, nargs="?", default=30)
    parser.add_argument("--app-id", type=int)
    parser.add_argument("--mode", choices=["incremental", "full"], default="incremental")
    return parser.parse_args()


def main():
    args = parse_args()

    games = read_games(args.app_id)
    grand_total = 0
    incomplete = []

    with psycopg.connect(DSN) as conn:
        for app_id, name in games:
            total, completed = collect(conn, app_id, name, args.max_pages, args.mode)
            grand_total += total
            if not completed:
                incomplete.append(name)

    print(f"\nвсего: {grand_total}")

    if incomplete:
        print(f"не докачано: {', '.join(incomplete)}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
