"""Запуск dbt под общим замком: две одновременные пересборки витрин роняют друг друга на переименовании таблиц."""

import os
import subprocess
import sys

from locks import core_lock

# Airflow держит свой dbt в отдельном venv, у web и worker он в PATH
DBT_BIN = os.getenv("DBT_BIN") or "dbt"


def main():
    with core_lock():
        result = subprocess.run([DBT_BIN, *sys.argv[1:]])

    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
