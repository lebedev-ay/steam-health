import os
import re
import uuid

import psycopg
from psycopg.rows import dict_row
from flask import Flask, render_template, jsonify, request
from celery.result import AsyncResult

from db import DSN
from change_points import (always_shown, attach_events, build_events,
                           build_series, find_change_points)
from tasks import (celery_app, collect_game, redis_client,
                   LOCK_KEY, LOCK_TTL, COLLECT_REVIEW_PAGES,
                   COLLECT_REVIEW_DAYS)

app = Flask(__name__)


def query(sql, params=()):
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        return conn.execute(sql, params).fetchall()


# границы параметров /api/data. Верхняя граница сглаживания - порядок длины ряда у тихой игры; за ней окно накрывает всю историю целиком
SMOOTHING_MAX_DAYS = 91
SENSITIVITY_MIN = 0.1
SENSITIVITY_MAX = 10
MIN_WEIGHT_MAX = 1000


# защита /api/collect от случайного запроса, не от целенаправленного: токен уезжает в html страницы. Настоящая защита - basic auth на обратном прокси (Caddy)
COLLECT_TOKEN = os.getenv("COLLECT_TOKEN", "")


# какую игру открывать при заходе на дашборд; пусто - первая по алфавиту. Существование не проверяется: чужой id просто не совпадёт ни с одним вариантом
DEFAULT_APP_ID = os.getenv("DEFAULT_APP_ID", "")


def list_games():
    return query("""
        select app_id, game_name, collection_status
        from marts.dim_game_current
        order by game_name
    """)


APP_ID_RE = re.compile(r"store\.steampowered\.com/app/(\d+)")


def parse_app_id(raw):
    raw = str(raw or "").strip()
    m = APP_ID_RE.search(raw)
    if m:
        return int(m.group(1))
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return None


@app.route("/")
def index():
    return render_template("index.html", games=list_games(),
                           collect_token=COLLECT_TOKEN,
                           default_app_id=DEFAULT_APP_ID,
                           review_pages=COLLECT_REVIEW_PAGES,
                           review_days=COLLECT_REVIEW_DAYS)


@app.route("/api/games")
def games():
    return jsonify(list_games())


@app.route("/api/collect", methods=["POST"])
def start_collect():
    if COLLECT_TOKEN and request.headers.get("X-Collect-Token") != COLLECT_TOKEN:
        return jsonify({"error": "нужен заголовок X-Collect-Token"}), 401

    body = request.get_json(silent=True) or {}
    app_id = parse_app_id(body.get("app_id"))
    mode = body.get("mode", "incremental")

    if app_id is None:
        return jsonify({"error": "некорректный ID игры или ссылка"}), 400
    if mode not in ("incremental", "full"):
        return jsonify({"error": "некорректный режим сбора"}), 400

    task_id = uuid.uuid4().hex
    # nx=True - проверка и установка одной атомарной операцией: без него два одновременных запроса оба увидели бы "замка нет" и оба прошли бы дальше
    ok = redis_client.set(LOCK_KEY, task_id, nx=True, ex=LOCK_TTL)
    if not ok:
        return jsonify({
            "error": "сейчас идёт сбор другой игры",
            "busy_task_id": redis_client.get(LOCK_KEY),
        }), 409

    collect_game.apply_async(args=[app_id, mode], task_id=task_id)
    return jsonify({"task_id": task_id})


@app.route("/api/task/<task_id>")
def task_status(task_id):
    result = AsyncResult(task_id, app=celery_app)
    response = {"state": result.state}

    if result.state == "PROGRESS":
        response["meta"] = result.info
    elif result.state == "SUCCESS":
        response["result"] = result.result
    elif result.state == "FAILURE":
        response["error"] = str(result.info)

    return jsonify(response)


def parse_params(args):
    try:
        app_id = int(args.get("app_id"))
    except (TypeError, ValueError):
        return None, {"error": "app_id должен быть числом"}

    smoothing = args.get("smoothing", "auto")
    if smoothing not in ("off", "auto"):
        try:
            days = int(smoothing)
        except ValueError:
            days = None
        if days is None or not 1 <= days <= SMOOTHING_MAX_DAYS:
            return None, {
                "error": f"smoothing - off, auto или целое от 1 до {SMOOTHING_MAX_DAYS}"
            }

    try:
        min_weight = float(args.get("min_weight", 0))
    except ValueError:
        min_weight = None
    if min_weight is None or not 0 <= min_weight <= MIN_WEIGHT_MAX:
        return None, {"error": f"min_weight - число от 0 до {MIN_WEIGHT_MAX}"}

    try:
        sensitivity = float(args.get("sensitivity", 1.5))
    except ValueError:
        sensitivity = None
    if sensitivity is None or not SENSITIVITY_MIN <= sensitivity <= SENSITIVITY_MAX:
        return None, {
            "error": f"sensitivity - число от {SENSITIVITY_MIN} до {SENSITIVITY_MAX}"
        }

    return (app_id, smoothing, min_weight, sensitivity), None


@app.route("/api/data")
def data():
    params, error = parse_params(request.args)
    if error:
        return jsonify(error), 400
    app_id, smoothing, min_weight, sensitivity = params

    smoothed, raw_daily, half, median = build_series(app_id, smoothing)
    if not raw_daily:
        return jsonify({
            "daily": [], "events": [], "change_points": [],
            "change_points_note": "по этой игре ещё нет собранных отзывов",
            "platform_events": [], "window": 0, "median_volume": 0
        })

    cp_events, events, platform_events, responsive_days = build_events(
        app_id, raw_daily, min_weight)

    change_points, cp_note = find_change_points(smoothed, sensitivity=sensitivity)

    return jsonify({
        "daily": smoothed,
        "window": half * 2 + 1,
        "median_volume": median,
        "events": [
            {"day": r["day"].isoformat(), "type": r["event_type"],
             "title": r["title"],
             "weight": float(r["weight"]) if r["weight"] is not None else None,
             "always_show": always_shown(r, responsive_days)}
            for r in events
        ],
        "platform_events": [
            {"date": e["event_date"].isoformat(), "type": e["event_type"],
             "title": e["title"]}
            for e in platform_events
        ],
        "change_points": attach_events(change_points, smoothed,
                                       cp_events, platform_events),
        "change_points_note": cp_note,
    })
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)