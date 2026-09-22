"""Запуск dbt под общим замком: две одновременные пересборки витрин роняют друг друга на переименовании таблиц."""

import os
import subprocess
import sys
from contextlib import nullcontext

from locks import core_lock

# Airflow держит свой dbt в отдельном venv, у web и worker он в PATH
DBT_BIN = os.getenv("DBT_BIN") or "dbt"


def main():

    # ставит только вызывающий, который уже держит замок ядра (web/tasks.py).
    # в окружение контейнера не выносить: это отключит замок для всех вызовов обёртки
    held = bool(os.getenv("CORE_LOCK_HELD"))

    with nullcontext() if held else core_lock():
        result = subprocess.run([DBT_BIN, *sys.argv[1:]])

    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
