import os
import sys
import json

import requests
import psycopg
from dotenv import load_dotenv

load_dotenv()

DSN = (
    f"host=localhost port=5433 "
    f"dbname={os.getenv('POSTGRES_DB')} "
    f"user={os.getenv('POSTGRES_USER')} "
    f"password={os.getenv('POSTGRES_PASSWORD')}"
)

URL = "https://store.steampowered.com/api/appdetails"


def fetch(app_id: int):
    response = requests.get(
        URL,
        params={"appids": app_id, "cc": "us", "l": "english"},
        timeout=30,
    )
    return response.status_code, response.json() if response.ok else None


def save(app_id: int, status: int, payload):
    with psycopg.connect(DSN) as conn:
        conn.execute(
            "insert into raw.appdetails (app_id, http_status, payload) values (%s, %s, %s)",
            (app_id, status, json.dumps(payload) if payload else None),
        )
        conn.commit()


def main():
    app_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1245620

    status, payload = fetch(app_id)
    print(f"app_id={app_id} status={status}")

    save(app_id, status, payload)
    print("saved")


if __name__ == "__main__":
    main()