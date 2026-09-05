import hashlib
from pathlib import Path

import psycopg

from db import DSN

MIGRATIONS_DIR = Path(__file__).parent.parent / "db" / "migration"

HISTORY_DDL = """
create table if not exists public.schema_history (
    version     text primary key,
    filename    text not null,
    checksum    text not null,
    applied_at  timestamptz not null default now()
)
"""


def main():
    # sorted() по умолчанию сравнивает имена файлов как строки: V10 < V1 < V2 лексикографически, реальный порядок миграций ломается на чистой базе. Сортируем по числу версии
    files = sorted(
        MIGRATIONS_DIR.glob("V*.sql"),
        key=lambda p: int(p.name.split("__")[0][1:]),
    )

    with psycopg.connect(DSN) as conn:
        conn.execute(HISTORY_DDL)
        conn.commit()

        applied = {
            row[0]: row[1]
            for row in conn.execute("select version, checksum from public.schema_history")
        }

        for path in files:
            version = path.name.split("__")[0]
            body = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(body.encode()).hexdigest()[:16]

            if version in applied:
                if applied[version] != checksum:
                    raise SystemExit(f"{path.name}: файл изменён после применения")
                print(f"skip  {path.name}")
                continue

            print(f"apply {path.name}")
            conn.execute(body)
            conn.execute(
                "insert into public.schema_history (version, filename, checksum) values (%s, %s, %s)",
                (version, path.name, checksum),
            )
            conn.commit()

    print("done")


if __name__ == "__main__":
    main()