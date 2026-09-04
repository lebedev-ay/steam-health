import os

import psycopg
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5433")

DSN = (
    f"host={DB_HOST} port={DB_PORT} "
    f"dbname={os.getenv('POSTGRES_DB')} "
    f"user={os.getenv('POSTGRES_USER')} "
    f"password={os.getenv('POSTGRES_PASSWORD')}"
)


def read_games(app_id=None):
    # состав игр - те, по которым уже есть сырьё в raw.appdetails.
    # Имя берётся из ядра; пока игра туда не загружена, вместо имени
    # идёт app_id. Явный app_id возвращается всегда, даже если игры
    # в базе ещё нет - так заводится новая
    with psycopg.connect(DSN) as conn:
        if app_id is not None:
            row = conn.execute(
                "select game_name from core.dim_game "
                "where app_id = %s and is_current",
                (app_id,),
            ).fetchone()
            return [(app_id, row[0] if row else str(app_id))]

        rows = conn.execute("""
            select a.app_id, g.game_name
            from (select distinct app_id from raw.appdetails) a
            left join core.dim_game g
                   on g.app_id = a.app_id and g.is_current
            order by a.app_id
        """).fetchall()

    return [(app_id, name or str(app_id)) for app_id, name in rows]
