import os
import re
import uuid
from datetime import datetime

import psycopg
from psycopg.rows import dict_row
from flask import Flask, render_template, jsonify, request
from celery.result import AsyncResult

from db import DSN
from tasks import (celery_app, collect_game, redis_client,
                   LOCK_KEY, LOCK_TTL, COLLECT_REVIEW_PAGES)

app = Flask(__name__)


def query(sql, params=()):
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        return conn.execute(sql, params).fetchall()


# на ровном ряде разброс сдвигов нулевой, порог тоже, и нестрогое
# сравнение объявляло переломом каждый день с нулевым сдвигом
MIN_SHIFT_PP = 1.0
MIN_SCORED_DAYS = 30

# границы параметров /api/data. Верхняя граница сглаживания - порядок
# длины ряда у тихой игры; за ней окно накрывает всю историю целиком
SMOOTHING_MAX_DAYS = 91
SENSITIVITY_MIN = 0.1
SENSITIVITY_MAX = 10
MIN_WEIGHT_MAX = 1000


def find_change_points(smoothed, half_window=7, min_gap=7, sensitivity=1.5):
    """
    Ищет точки перелома: где среднее ПОСЛЕ заметно отличается
    от среднего ДО. sensitivity - сколько сигм считать переломом.
    Возвращает найденные точки и причину, если искать было не на чем.
    """
    n = len(smoothed)
    scores = [None] * n

    for i in range(n):
        before = [s["pct"] for s in smoothed[max(0, i - half_window):i]
                  if s["pct"] is not None]
        after = [s["pct"] for s in smoothed[i:i + half_window]
                 if s["pct"] is not None]

        if len(before) < half_window // 2 or len(after) < half_window // 2:
            continue

        scores[i] = sum(after) / len(after) - sum(before) / len(before)

    clean = [abs(s) for s in scores if s is not None]
    if len(clean) < MIN_SCORED_DAYS:
        return [], (f"мало данных: сдвиг посчитан для {len(clean)} дней из {n}, "
                    f"детектору нужно не меньше {MIN_SCORED_DAYS}")

    mean = sum(clean) / len(clean)
    var = sum((x - mean) ** 2 for x in clean) / len(clean)
    threshold = mean + sensitivity * (var ** 0.5)

    candidates = [
        (i, scores[i]) for i in range(n)
        if scores[i] is not None
        and abs(scores[i]) > threshold
        and abs(scores[i]) >= MIN_SHIFT_PP
    ]
    candidates.sort(key=lambda x: -abs(x[1]))

    chosen = []
    for i, score in candidates:
        if all(abs(i - j) >= min_gap for j, _ in chosen):
            chosen.append((i, score))

    return sorted(chosen), None


# см. decisions.md, запись 022 - почему перелом бывает необъяснимым
SIGNIFICANT_WEIGHT = 2
SIGNIFICANT_TYPES = {"patch", "season_start", "expansion"}

# защита /api/collect от случайного запроса, не от целенаправленного:
# токен уезжает в html страницы. Настоящая защита - basic auth в nginx
COLLECT_TOKEN = os.getenv("COLLECT_TOKEN", "")


def is_significant_event(e):
    return (e["weight"] is not None and e["weight"] >= SIGNIFICANT_WEIGHT) \
        or e["event_type"] in SIGNIFICANT_TYPES


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
                           review_pages=COLLECT_REVIEW_PAGES)


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
    # nx=True - проверка и установка одной атомарной операцией:
    # без него два одновременных запроса оба увидели бы "замка нет"
    # и оба прошли бы дальше
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


@app.route("/api/data")
def data():
    try:
        app_id = int(request.args.get("app_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "app_id должен быть числом"}), 400

    smoothing = request.args.get("smoothing", "auto")
    if smoothing not in ("off", "auto"):
        try:
            days = int(smoothing)
        except ValueError:
            days = None
        if days is None or not 1 <= days <= SMOOTHING_MAX_DAYS:
            return jsonify({
                "error": f"smoothing - off, auto или целое от 1 до {SMOOTHING_MAX_DAYS}"
            }), 400

    try:
        min_weight = float(request.args.get("min_weight", 0))
    except ValueError:
        min_weight = None
    if min_weight is None or not 0 <= min_weight <= MIN_WEIGHT_MAX:
        return jsonify({"error": f"min_weight - число от 0 до {MIN_WEIGHT_MAX}"}), 400

    try:
        sensitivity = float(request.args.get("sensitivity", 1.5))
    except ValueError:
        sensitivity = None
    if sensitivity is None or not SENSITIVITY_MIN <= sensitivity <= SENSITIVITY_MAX:
        return jsonify({
            "error": f"sensitivity - число от {SENSITIVITY_MIN} до {SENSITIVITY_MAX}"
        }), 400

    raw_daily = query("""
        with bounds as (
            select min(created_date) as d_from, max(created_date) as d_to
            from marts.review_flat
            where app_id = %s
        ),
        calendar as (
            select generate_series(d_from, d_to, interval '1 day')::date as day
            from bounds
        ),
        actual as (
            select created_date as day,
                   count(*) as total,
                   count(*) filter (where voted_up) as positive
            from marts.review_flat
            where app_id = %s
            group by 1
        )
        select c.day,
               coalesce(a.total, 0) as total,
               coalesce(a.positive, 0) as positive
        from calendar c
        left join actual a on a.day = c.day
        order by c.day
    """, (app_id, app_id))

    if not raw_daily:
        return jsonify({
            "daily": [], "events": [], "change_points": [],
            "change_points_note": "по этой игре ещё нет собранных отзывов",
            "platform_events": [], "window": 0, "median_volume": 0
        })

    # ширина окна: обратно пропорциональна медианному объёму
    volumes = sorted(r["total"] for r in raw_daily)
    median = volumes[len(volumes) // 2]

    if smoothing == "off":
        half = 0
    elif smoothing == "auto":
        if median >= 100:
            half = 1      # окно 3 дня
        elif median >= 30:
            half = 3      # окно 7 дней
        elif median >= 10:
            half = 7      # окно 15 дней
        else:
            half = 14     # окно 29 дней
    else:
        half = int(smoothing) // 2

    smoothed = []
    for i, row in enumerate(raw_daily):
        lo = max(0, i - half)
        hi = min(len(raw_daily), i + half + 1)
        window = raw_daily[lo:hi]

        pos = sum(w["positive"] for w in window)
        tot = sum(w["total"] for w in window)

        smoothed.append({
            "day": row["day"].isoformat(),
            "total": row["total"],
            "pct": round(100 * pos / tot, 1) if tot else None,
            "window_n": tot,
        })

    # база: медиана сглаженной доли за предыдущие 90 дней
    BASE_DAYS = 90
    for i, row in enumerate(smoothed):
        if row["pct"] is None:
            row["delta"] = None
            row["base"] = None
            continue

        lo = max(0, i - BASE_DAYS)
        history = [s["pct"] for s in smoothed[lo:i] if s["pct"] is not None]

        if len(history) < 14:
            row["delta"] = None
            row["base"] = None
        else:
            base = sorted(history)[len(history) // 2]
            row["base"] = base
            row["delta"] = round(row["pct"] - base, 1)

    # без фильтров по типу и весу: скрытый на графике тип и слабый
    # патч тоже могут оказаться причиной перелома.
    # distinct: Steam выпускает один анонс под несколькими gid,
    # на графике такому событию положен один маркер
    cp_events = query("""
        select distinct
               (p.published_at at time zone 'utc')::date as day,
               p.event_type,
               p.title,
               p.weight
        from core.fct_patch p
        join core.dim_game g on g.game_sk = p.game_sk
        where g.app_id = %s
        order by 1
    """, (app_id,))

    # маркеры на графике - те же события с порогом значимости
    # из формы, подмножество cp_events: второй запрос не нужен.
    # Пустой вес считается нулём, как и на клиенте: иначе событие
    # без веса проходило бы любой порог
    events = [e for e in cp_events if (e["weight"] or 0) >= min_weight]

    # общие для всех игр, не зависят от app_id. Дата приблизительная
    # (по публикации заметки) - см. decisions.md, запись 023
    platform_events = query("""
        select event_date, event_type, title
        from core.dim_platform_event
        where event_date >= %s and event_date <= %s
        order by event_date
    """, (raw_daily[0]["day"], raw_daily[-1]["day"]))

    change_points, cp_note = find_change_points(smoothed, sensitivity=sensitivity)

    cp_out = []
    for idx, score in change_points:
        day = smoothed[idx]["day"]
        day_date = datetime.fromisoformat(day).date()

        nearby = [
            e for e in cp_events
            if abs((e["day"] - day_date).days) <= 3
        ]
        major = [e for e in nearby if is_significant_event(e)]
        minor = [e for e in nearby if not is_significant_event(e)]

        platform_nearby = [
            e for e in platform_events
            if abs((e["event_date"] - day_date).days) <= 3
        ]
        platform_event = None
        if platform_nearby:
            closest = min(platform_nearby,
                          key=lambda e: abs((e["event_date"] - day_date).days))
            platform_event = {
                "date": closest["event_date"].isoformat(),
                "type": closest["event_type"],
                "title": closest["title"],
            }

        cp_out.append({
            "day": day,
            "score": round(score, 1),
            "events": [
                {"type": e["event_type"], "title": e["title"],
                 "weight": float(e["weight"]) if e["weight"] is not None else None}
                for e in major
            ],
            "events_minor": [
                {"type": e["event_type"], "title": e["title"]}
                for e in minor
            ],
            "platform_event": platform_event,
        })

    return jsonify({
        "daily": smoothed,
        "window": half * 2 + 1,
        "median_volume": median,
        "events": [
            {"day": r["day"].isoformat(), "type": r["event_type"],
             "title": r["title"],
             "weight": float(r["weight"]) if r["weight"] is not None else None}
            for r in events
        ],
        "platform_events": [
            {"date": e["event_date"].isoformat(), "type": e["event_type"],
             "title": e["title"]}
            for e in platform_events
        ],
        "change_points": cp_out,
        "change_points_note": cp_note,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)