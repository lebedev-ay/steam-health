import argparse
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from db import DSN, read_games

# события за прошлые годы должны находить свою версию, иначе улетят
# в заглушку Unknown - см. decisions.md, запись 006
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


def extract_links(payload, app_id):
    data = payload[str(app_id)]["data"]

    return {
        "developer": data.get("developers") or [],
        "publisher": data.get("publishers") or [],
        # id жанра Steam отдаёт строкой, id категории числом
        "genres": [(int(g["id"]), g["description"]) for g in data.get("genres") or []],
        "categories": [(int(c["id"]), c["description"])
                       for c in data.get("categories") or []],
    }


def find_company_sk(conn, company_name):
    conn.execute(
        """
        insert into core.dim_company (company_name)
        values (%s)
        on conflict (company_name) do nothing
        """,
        (company_name,),
    )
    row = conn.execute(
        "select company_sk from core.dim_company where company_name = %s",
        (company_name,),
    ).fetchone()
    return row["company_sk"]


def load_links(conn, game_sk, links):
    # мосты переписываются целиком под этот game_sk: у новой версии SCD2
    # они свои, у закрытых остаются те, что были на их момент
    conn.execute("delete from core.bridge_game_company where game_sk = %s", (game_sk,))
    conn.execute("delete from core.bridge_game_genre where game_sk = %s", (game_sk,))
    conn.execute("delete from core.bridge_game_category where game_sk = %s", (game_sk,))

    for role in ("developer", "publisher"):
        for company_name in links[role]:
            conn.execute(
                """
                insert into core.bridge_game_company (game_sk, company_sk, role)
                values (%s, %s, %s)
                on conflict do nothing
                """,
                (game_sk, find_company_sk(conn, company_name), role),
            )

    for genre_sk, genre_name in links["genres"]:
        conn.execute(
            """
            insert into core.dim_genre (genre_sk, genre_name)
            values (%s, %s)
            on conflict (genre_sk) do update set genre_name = excluded.genre_name
            """,
            (genre_sk, genre_name),
        )
        conn.execute(
            """
            insert into core.bridge_game_genre (game_sk, genre_sk)
            values (%s, %s)
            on conflict do nothing
            """,
            (game_sk, genre_sk),
        )

    for category_sk, category_name in links["categories"]:
        conn.execute(
            """
            insert into core.dim_category (category_sk, category_name)
            values (%s, %s)
            on conflict (category_sk) do update set category_name = excluded.category_name
            """,
            (category_sk, category_name),
        )
        conn.execute(
            """
            insert into core.bridge_game_category (game_sk, category_sk)
            values (%s, %s)
            on conflict do nothing
            """,
            (game_sk, category_sk),
        )


def insert_version(conn, fields, valid_from):
    columns = ", ".join(ALL_FIELDS)
    placeholders = ", ".join(["%s"] * len(ALL_FIELDS))
    values = [fields[c] for c in ALL_FIELDS]

    row = conn.execute(
        f"""
        insert into core.dim_game ({columns}, valid_from, is_current)
        values ({placeholders}, %s, true)
        returning game_sk
        """,
        values + [valid_from],
    ).fetchone()
    return row["game_sk"]


def load(conn, fields):
    current = conn.execute(
        "select * from core.dim_game where app_id = %s and is_current",
        (fields["app_id"],),
    ).fetchone()

    if current is None:
        return insert_version(conn, fields, FIRST_VERSION_FROM), "created"

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
        return current["game_sk"], "unchanged"

    changed_at = datetime.now(timezone.utc)

    conn.execute(
        """
        update core.dim_game
        set valid_to = %s, is_current = false
        where game_sk = %s
        """,
        (changed_at, current["game_sk"]),
    )

    return insert_version(conn, fields, changed_at), f"new version ({', '.join(changed)})"


def load_one(conn, app_id, name):
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
        return None

    payload = row["payload"]
    info = payload.get(str(app_id)) or {}
    if not info.get("success") or "data" not in info:
        print(f"{name}: Steam не вернул данные (success={info.get('success')})")
        return None

    fields = extract(payload, app_id)
    game_sk, result = load(conn, fields)
    load_links(conn, game_sk, extract_links(payload, app_id))
    conn.commit()

    print(f"{name}: {result}")
    return result


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-id", type=int)
    return parser.parse_args()


def main():
    args = parse_args()
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        for app_id, name in read_games(args.app_id):
            load_one(conn, app_id, name)


if __name__ == "__main__":
    main()