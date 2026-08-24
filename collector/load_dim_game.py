import sys
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from db import DSN, read_games

# Первая версия игры получает открытую нижнюю границу:
# игра существовала до начала сбора, и события за прошлые годы
# должны находить свою версию. См. docs/decisions.md, запись 006
FIRST_VERSION_FROM = datetime(2000, 1, 1, tzinfo=timezone.utc)

TRACKED = (
    "app_type", "is_free", "required_age",
    "metacritic_score", "is_coming_soon",
    "release_date_raw", "release_date_parsed",
)

ALL_FIELDS = ("app_id", "game_name", "metacritic_url") + TRACKED


def parse_release_date(raw):
    if not raw:
        return None
    for fmt in ("%d %b, %Y", "%b %d, %Y", "%d %B, %Y", "%B %d, %Y", "%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def extract(payload, app_id):
    data = payload[str(app_id)]["data"]
    release = data.get("release_date") or {}
    raw_date = release.get("date")
    metacritic = data.get("metacritic") or {}

    return {
        "app_id": app_id,
        "game_name": data.get("name"),
        "app_type": data.get("type"),
        "is_free": data.get("is_free"),
        "required_age": int(data.get("required_age") or 0),
        "metacritic_score": metacritic.get("score"),
        "metacritic_url": metacritic.get("url"),
        "is_coming_soon": release.get("coming_soon", False),
        "release_date_raw": raw_date,
        "release_date_parsed": parse_release_date(raw_date),
    }


def insert_version(conn, fields, valid_from):
    columns = ", ".join(ALL_FIELDS)
    placeholders = ", ".join(["%s"] * len(ALL_FIELDS))
    values = [fields[c] for c in ALL_FIELDS]

    conn.execute(
        f"""
        insert into core.dim_game ({columns}, valid_from, is_current)
        values ({placeholders}, %s, true)
        """,
        values + [valid_from],
    )


def load(conn, fields):
    current = conn.execute(
        "select * from core.dim_game where app_id = %s and is_current",
        (fields["app_id"],),
    ).fetchone()

    if current is None:
        insert_version(conn, fields, FIRST_VERSION_FROM)
        return "created"

    changed = [f for f in TRACKED if current[f] != fields[f]]

    if not changed:
        conn.execute(
            """
            update core.dim_game
            set game_name = %s, metacritic_url = %s
            where game_sk = %s
            """,
            (fields["game_name"], fields["metacritic_url"], current["game_sk"]),
        )
        return "unchanged"

    changed_at = datetime.now(timezone.utc)

    conn.execute(
        """
        update core.dim_game
        set valid_to = %s, is_current = false
        where game_sk = %s
        """,
        (changed_at, current["game_sk"]),
    )
    insert_version(conn, fields, changed_at)

    return f"new version ({', '.join(changed)})"


def main():
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        for app_id, name in read_games():
            row = conn.execute(
                """
                select payload from raw.appdetails
                where app_id = %s and payload is not null
                order by fetched_at desc limit 1
                """,
                (app_id,),
            ).fetchone()

            if row is None:
                print(f"{name}: нет сырых данных")
                continue

            payload = row["payload"]
            data = payload[str(app_id)]["data"]
            fields = extract(payload, app_id)
            result = load(conn, fields)
            conn.commit()

            print(f"{name}: {result}")


if __name__ == "__main__":
    main()