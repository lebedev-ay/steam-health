import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DSN = (
    f"host=localhost port=5433 "
    f"dbname={os.getenv('POSTGRES_DB')} "
    f"user={os.getenv('POSTGRES_USER')} "
    f"password={os.getenv('POSTGRES_PASSWORD')}"
)

GAMES = Path(__file__).parent / "games.txt"


def read_games():
    games = []
    for line in GAMES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        app_id, name = line.split(maxsplit=1)
        games.append((int(app_id), name))
    return games
