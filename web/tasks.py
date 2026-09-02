import os
import subprocess
from pathlib import Path

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

DBT_PROJECT_DIR = Path(
    os.getenv("DBT_PROJECT_DIR", Path(__file__).parent.parent / "dbt")
)

# сколько страниц берёт сбор из дашборда: отзывы по 100 на страницу,
# новости по 500. Для более глубокой выкачки - коллекторы напрямую
COLLECT_REVIEW_PAGES = int(os.getenv("COLLECT_REVIEW_PAGES", 30))
COLLECT_NEWS_PAGES = int(os.getenv("COLLECT_NEWS_PAGES", 10))

celery_app = Celery("tasks", broker=REDIS_URL, backend=REDIS_URL)
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

TOTAL_STEPS = 8

LOCK_KEY = "collect:lock"
LOCK_TTL = 15 * 60

# снимаем замок, только если в нём всё ещё id этой задачи: иначе
# после истечения TTL finally снёс бы чужой, уже активный замок
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
            # если что-то дальше упадёт, статус останется 'partial'
            conn.execute(
                "update core.dim_game set collection_status = 'partial' "
                "where app_id = %s and is_current",
                (app_id,),
            )
            conn.commit()

        progress(4, f"{name}: качаю новости ({mode})")
        with psycopg.connect(DSN) as conn:
            _, completed = fetch_news.collect(conn, app_id, name,
                                              COLLECT_NEWS_PAGES, mode)
        if not completed:
            raise RuntimeError(f"{name}: не удалось докачать новости (шаг 4) - статус остаётся partial")

        progress(5, f"{name}: качаю отзывы ({mode})")
        with psycopg.connect(DSN) as conn:
            def on_page(page, total):
                # продлеваем на каждой странице: дёшево, а замок
                # не должен истечь посреди реальной работы
                redis_client.expire(LOCK_KEY, LOCK_TTL)
                progress(5, f"{name}: качаю отзывы ({mode})", progress=f"{page} стр., {total} отзывов")

            _, completed = fetch_reviews.collect(conn, app_id, name,
                                                 COLLECT_REVIEW_PAGES, mode,
                                                 on_page=on_page)
        if not completed:
            raise RuntimeError(f"{name}: не удалось докачать отзывы (шаг 5) - статус остаётся partial")

        progress(6, f"{name}: загружаю отзывы в core")
        with psycopg.connect(DSN, row_factory=dict_row) as conn:
            load_fct_review.load_all(conn, app_id)

        progress(7, f"{name}: загружаю патчи")
        with psycopg.connect(DSN, row_factory=dict_row) as conn:
            load_fct_patch.load_all(conn, app_id)
            conn.commit()

        progress(8, f"{name}: пересобираю витрины (dbt run)")
        # без --select: модели связаны, выборочная сборка рассогласует
        # витрины с ядром, а экономии почти нет - decisions.md, запись 026
        # heartbeat из on_page сюда не доходит - продлеваем замок явно
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
        # замок снимается всегда - и при успехе, и при падении на любом
        # шаге, иначе следующий сбор будет ждать LOCK_TTL впустую
        redis_client.eval(_RELEASE_LOCK_SCRIPT, 1, LOCK_KEY, self.request.id)
