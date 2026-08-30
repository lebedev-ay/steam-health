import os
from pathlib import Path

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

GAMES = Path(__file__).parent / "games.txt"


def read_games(app_id=None):
    games = []
    for line in GAMES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line_app_id, name = line.split(maxsplit=1)
        games.append((int(line_app_id), name))

    if app_id is None:
        return games

    for gid, name in games:
        if gid == app_id:
            return [(gid, name)]

    return [(app_id, str(app_id))]
