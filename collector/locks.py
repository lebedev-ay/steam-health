"""Общий замок на запись в ядро и пересборку витрин: кнопка дашборда и ночной прогон не должны совпасть."""

import os
import time
from contextlib import contextmanager

import psycopg

from db import DSN

# ключ один на весь проект, все точки входа обязаны брать его одинаковым - иначе разойдутся по разным замкам и защиты не будет.
# Значение произвольное, это crc32("steam-health:core"): лишь бы не столкнуться с чужим advisory-замком в той же базе
CORE_LOCK_KEY = 383874548

# полная загрузка в ядро с пересборкой витрин укладывается в единицы минут, получаса хватает с многократным запасом.
# or, а не второй аргумент getenv: compose подставляет пустую строку, когда переменной нет в .env
LOCK_TIMEOUT = int(os.getenv("CORE_LOCK_TIMEOUT") or 30 * 60)

POLL_SECONDS = 5


class LockBusy(RuntimeError):
    pass


def holder_pid(conn, key):
    # ключ-bigint лежит в pg_locks разложенным на два слова, objsubid отличает его от двухаргументной формы замка
    row = conn.execute(
        """
        select pid from pg_locks
        where locktype = 'advisory'
          and objsubid = 1
          and ((classid::bigint << 32) | objid::bigint) = %s
          and granted
        """,
        (key,),
    ).fetchone()
    return row[0] if row else None


@contextmanager
def core_lock(timeout=None, on_wait=None, key=CORE_LOCK_KEY):
    """Ждёт замок не дольше timeout, на выходе отпускает - в том числе при исключении.

    Соединение своё, а не рабочее: рабочее по ходу закрывается и откатывается, а замок должен дожить до конца работы.
    Убирать за собой после падения процесса не нужно: Postgres отпускает замок, когда закрывается соединение.
    """
    timeout = LOCK_TIMEOUT if timeout is None else timeout

    with psycopg.connect(DSN, autocommit=True) as conn:
        started = time.monotonic()
        announced = False

        while not conn.execute("select pg_try_advisory_lock(%s)", (key,)).fetchone()[0]:
            waited = time.monotonic() - started
            if waited >= timeout:
                raise LockBusy(
                    f"ядро занято другим прогоном: замок {key} не освободился за {timeout} с, работа не начата"
                )

            if not announced:
                print(f"ядро занято процессом {holder_pid(conn, key)}, жду освобождения (до {timeout} с)", flush=True)
                announced = True

            # пока ждём, вызывающий код продлевает то, что у него истекает по времени
            if on_wait:
                on_wait()

            time.sleep(min(POLL_SECONDS, timeout - waited))

        if announced:
            print(f"замок получен, ждали {round(time.monotonic() - started)} с", flush=True)

        try:
            yield
        finally:
            conn.execute("select pg_advisory_unlock(%s)", (key,))
