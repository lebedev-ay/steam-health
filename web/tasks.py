import os
import subprocess
import sys
from pathlib import Path

# В образе collector/ лежит рядом с этим файлом (web/collector,
# см. web/Dockerfile); при локальном запуске из репозитория —
# на уровень выше (../collector, web/ и collector/ соседи).
for _candidate in (Path(__file__).parent / "collector",
                    Path(__file__).parent.parent / "collector"):
    # существование каталога не гарантирует, что это тот collector/ —
    # пустой каталог (например, случайно созданный Docker-ом) тоже
    # проходит is_dir(). Ищем конкретный файл, который там точно есть
    if (_candidate / "db.py").is_file():
        sys.path.insert(0, str(_candidate))
        break

# та же логика, что для collector/ выше, — dbt/ ищем тем же способом
# и по тем же двум расположениям (образ / локальный репозиторий)
DBT_PROJECT_DIR = None
for _candidate in (Path(__file__).parent / "dbt",
                    Path(__file__).parent.parent / "dbt"):
    if (_candidate / "dbt_project.yml").is_file():
        DBT_PROJECT_DIR = _candidate
        break

import psycopg
import redis
from psycopg.rows import dict_row
from celery import Celery

import fetch_appdetails
import load_dim_game
import fetch_news
import fetch_reviews
import load_fct_review
import load_fct_patch
from db import DSN

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("tasks", broker=REDIS_URL, backend=REDIS_URL)
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

TOTAL_STEPS = 8

LOCK_KEY = "collect:lock"
LOCK_TTL = 15 * 60

# безопасное снятие замка: удаляем, только если значение в нём —
# всё ещё id этой самой задачи. Без проверки: если TTL истёк, пока
# задача ещё реально работала (сбой heartbeat, зависший dbt run),
# а другая задача уже успела встать на освободившийся замок — finally
# снёс бы уже чужой, активный замок
_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


@celery_app.task(bind=True)
def collect_game(self, app_id, mode="incremental"):
    def progress(step, message, **extra):
        meta = {"step": step, "total": TOTAL_STEPS, "message": message}
        meta.update(extra)
        self.update_state(state="PROGRESS", meta=meta)

    try:
        progress(1, "проверка игры в Steam")
        status, payload = fetch_appdetails.fetch(app_id)
        info = (payload or {}).get(str(app_id)) or {}

        if not info.get("success"):
            raise ValueError(f"appdetails не вернул данные для app_id {app_id}")

        data = info.get("data") or {}
        if data.get("type") != "game":
            raise ValueError(
                f"app_id {app_id} — это {data.get('type') or 'не приложение'}, а не игра"
            )

        name = data.get("name", str(app_id))

        progress(2, f"{name}: сохраняю appdetails")
        with psycopg.connect(DSN, row_factory=dict_row) as conn:
            fetch_appdetails.save(conn, app_id, status, payload)

            progress(3, f"{name}: обновляю dim_game")
            load_dim_game.load_one(conn, app_id, name)
            # с этого момента в dim_game есть строка на эту игру:
            # если что-то дальше упадёт, статус так и останется 'partial'
            conn.execute(
                "update core.dim_game set collection_status = 'partial' "
                "where app_id = %s and is_current",
                (app_id,),
            )
            conn.commit()

        progress(4, f"{name}: качаю новости ({mode})")
        with psycopg.connect(DSN) as conn:
            _, completed = fetch_news.collect(conn, app_id, name, 10, mode)
        if not completed:
            raise RuntimeError(f"{name}: не удалось докачать новости (шаг 4) — статус остаётся partial")

        progress(5, f"{name}: качаю отзывы ({mode})")
        with psycopg.connect(DSN) as conn:
            def on_page(page, total):
                # heartbeat: страницы качаются дольше, чем LOCK_TTL,
                # только у очень объёмных игр, но продлеваем на каждой —
                # дёшево, а замок не должен истечь посреди реальной работы
                redis_client.expire(LOCK_KEY, LOCK_TTL)
                progress(5, f"{name}: качаю отзывы ({mode})", progress=f"{page} стр., {total} отзывов")

            _, completed = fetch_reviews.collect(conn, app_id, name, 30, mode, on_page=on_page)
        if not completed:
            raise RuntimeError(f"{name}: не удалось докачать отзывы (шаг 5) — статус остаётся partial")

        progress(6, f"{name}: загружаю отзывы в core")
        with psycopg.connect(DSN, row_factory=dict_row) as conn:
            load_fct_review.load_all(conn, app_id)

        progress(7, f"{name}: загружаю патчи")
        with psycopg.connect(DSN, row_factory=dict_row) as conn:
            load_fct_patch.load_all(conn, app_id)
            conn.commit()

        progress(8, f"{name}: пересобираю витрины (dbt run)")
        if DBT_PROJECT_DIR is None:
            raise RuntimeError("каталог dbt/ не найден рядом с web/ ни в образе, ни в репозитории")
        # без --select: витрины строятся из общего набора моделей
        # (review_flat -> review_daily -> patch_impact), и выборочная
        # сборка одной из них рискует оставить остальные рассогласованными
        # с ядром. Полный dbt run и раньше, при refresh concurrently,
        # занимал время того же порядка (~7 минут, см. миграцию V24
        # и docs/decisions.md) — экономии на --select почти нет
        # heartbeat из on_page сюда не доходит (dbt run — не постраничный
        # сбор), поэтому продлеваем явно перед запуском
        redis_client.expire(LOCK_KEY, LOCK_TTL)
        result = subprocess.run(
            ["dbt", "run"],
            cwd=DBT_PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=900,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"dbt run упал (код {result.returncode}):\n"
                f"{result.stdout}\n{result.stderr}"
            )

        with psycopg.connect(DSN) as conn:
            conn.execute(
                "update core.dim_game set collection_status = 'complete' "
                "where app_id = %s and is_current",
                (app_id,),
            )
            conn.commit()

        return {"app_id": app_id, "name": name, "mode": mode}
    finally:
        # замок снимается всегда — и при успехе, и при падении на любом
        # шаге, иначе следующий сбор будет ждать LOCK_TTL впустую
        redis_client.eval(_RELEASE_LOCK_SCRIPT, 1, LOCK_KEY, self.request.id)
