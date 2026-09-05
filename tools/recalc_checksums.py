"""
Пересчёт контрольных сумм применённых миграций.
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "collector"))

import psycopg

from db import DSN

MIGRATIONS_DIR = Path(__file__).parent.parent / "db" / "migration"

# та же длина, что пишет migrate.py
CHECKSUM_LEN = 16


def main():
    files = {p.name.split("__")[0]: p for p in MIGRATIONS_DIR.glob("V*.sql")}
    updated = 0

    with psycopg.connect(DSN) as conn:
        applied = conn.execute(
            "select version, checksum from public.schema_history order by version"
        ).fetchall()

        for version, checksum in applied:
            path = files.get(version)
            if path is None:
                print(f"{version}: файла нет, пропуск")
                continue

            body = path.read_text(encoding="utf-8")
            actual = hashlib.sha256(body.encode()).hexdigest()[:CHECKSUM_LEN]
            if actual == checksum:
                continue

            conn.execute(
                "update public.schema_history set checksum = %s where version = %s",
                (actual, version),
            )
            print(f"{path.name}: {checksum} -> {actual}")
            updated += 1

        conn.commit()

    print(f"обновлено записей: {updated}")


if __name__ == "__main__":
    main()
