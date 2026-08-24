import time
from datetime import datetime, timezone

import requests
import psycopg
from psycopg.rows import dict_row

from db import DSN, read_games

URL = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"


def find_game_sk(conn, app_id, moment):
    row = conn.execute(
        """
        select game_sk from core.dim_game
        where app_id = %s and %s >= valid_from and %s < valid_to
        """,
        (app_id, moment, moment),
    ).fetchone()
    return row["game_sk"] if row else -1


def fetch_player_count(app_id):
    response = requests.get(
        URL,
        params={"appid": app_id},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["response"]["player_count"]


def collect(conn, app_id, name, measured_at):
    try:
        player_count = fetch_player_count(app_id)
    except Exception as e:
        print(f"{name}: ошибка: {e}")
        return

    game_sk = find_game_sk(conn, app_id, measured_at)
    date_sk = int(measured_at.strftime("%Y%m%d"))
    time_sk = measured_at.hour

    conn.execute(
        """
        insert into core.fct_player_count
            (game_sk, date_sk, time_sk, measured_at, player_count, is_on_sale)
        values (%s, %s, %s, %s, %s, %s)
        on conflict (game_sk, measured_at) do nothing
        """,
        (game_sk, date_sk, time_sk, measured_at, player_count, None),
    )
    conn.commit()

    print(f"{name}: {player_count}")


def main():
    measured_at = datetime.now(timezone.utc).replace(second=0, microsecond=0)

    games = read_games()

    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        for app_id, name in games:
            collect(conn, app_id, name, measured_at)
            time.sleep(1.5)


if __name__ == "__main__":
    main()
