import os
import sys
from pathlib import Path

# В образе collector/ лежит рядом с этим файлом (web/collector,
# см. web/Dockerfile); при локальном запуске из репозитория —
# на уровень выше (../collector, web/ и collector/ соседи).
for _candidate in (Path(__file__).parent / "collector",
                    Path(__file__).parent.parent / "collector"):
    if _candidate.is_dir():
        sys.path.insert(0, str(_candidate))
        break

import psycopg
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

TOTAL_STEPS = 7


@celery_app.task(bind=True)
def collect_game(self, app_id, mode="incremental"):
    def progress(step, message, **extra):
        meta = {"step": step, "total": TOTAL_STEPS, "message": message}
        meta.update(extra)
        self.update_state(state="PROGRESS", meta=meta)

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
    fetch_appdetails.save(app_id, status, payload)

    progress(3, f"{name}: обновляю dim_game")
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
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
        fetch_news.collect(conn, app_id, name, 10, mode)

    progress(5, f"{name}: качаю отзывы ({mode})")
    with psycopg.connect(DSN) as conn:
        def on_page(page, total):
            progress(5, f"{name}: качаю отзывы ({mode})", progress=f"{page} стр., {total} отзывов")

        fetch_reviews.collect(conn, app_id, name, 30, mode, on_page=on_page)

    progress(6, f"{name}: загружаю отзывы в core")
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        load_fct_review.load_all(conn, app_id)

    progress(7, f"{name}: загружаю патчи и обновляю витрину")
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        load_fct_patch.load_all(conn, app_id)
        # concurrently — чтобы не блокировать чтение patch_impact
        # дашбордом на время пересчёта (~7 минут на полный refresh,
        # см. миграцию V24 и docs/decisions.md)
        conn.execute("refresh materialized view concurrently marts.patch_impact")
        conn.execute(
            "update core.dim_game set collection_status = 'complete' "
            "where app_id = %s and is_current",
            (app_id,),
        )
        conn.commit()

    return {"app_id": app_id, "name": name, "mode": mode}
