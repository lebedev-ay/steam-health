import os
import re
from datetime import datetime

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, request
from celery.result import AsyncResult

from tasks import celery_app, collect_game

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5433")

DSN = (
    f"host={DB_HOST} port={DB_PORT} "
    f"dbname={os.getenv('POSTGRES_DB')} "
    f"user={os.getenv('POSTGRES_USER')} "
    f"password={os.getenv('POSTGRES_PASSWORD')}"
)

app = Flask(__name__)


def query(sql, params=()):
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        return conn.execute(sql, params).fetchall()


def find_change_points(smoothed, half_window=7, min_gap=7, sensitivity=1.5):
    """
    Ищет точки перелома: где среднее ПОСЛЕ заметно отличается
    от среднего ДО. sensitivity — сколько сигм считать переломом.
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
    if len(clean) < 30:
        return []

    mean = sum(clean) / len(clean)
    var = sum((x - mean) ** 2 for x in clean) / len(clean)
    threshold = mean + sensitivity * (var ** 0.5)

    candidates = [
        (i, scores[i]) for i in range(n)
        if scores[i] is not None and abs(scores[i]) >= threshold
    ]
    candidates.sort(key=lambda x: -abs(x[1]))

    chosen = []
    for i, score in candidates:
        if all(abs(i - j) >= min_gap for j, _ in chosen):
            chosen.append((i, score))

    return sorted(chosen)


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
    return render_template("index.html", games=list_games())


@app.route("/api/games")
def games():
    return jsonify(list_games())


@app.route("/api/collect", methods=["POST"])
def start_collect():
    body = request.get_json(silent=True) or {}
    app_id = parse_app_id(body.get("app_id"))
    mode = body.get("mode", "incremental")

    if app_id is None:
        return jsonify({"error": "некорректный ID игры или ссылка"}), 400
    if mode not in ("incremental", "full"):
        return jsonify({"error": "некорректный режим сбора"}), 400

    task = collect_game.delay(app_id, mode)
    return jsonify({"task_id": task.id})


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
    app_id = int(request.args.get("app_id"))
    smoothing = request.args.get("smoothing", "auto")
    min_weight = float(request.args.get("min_weight", 0))
    sensitivity = float(request.args.get("sensitivity", 1.5))

    # types не задан — отдаём все типы событий
    types = request.args.get("types", "")
    type_list = [t for t in types.split(",") if t]

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
            "window": 0, "median_volume": 0
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

    if type_list:
        events = query("""
            select distinct published_date as day, event_type, title, weight
            from marts.patch_impact
            where app_id = %s and window_code = 'after_7'
              and event_type = any(%s)
              and (weight is null or weight >= %s)
            order by 1
        """, (app_id, type_list, min_weight))
    else:
        events = query("""
            select distinct published_date as day, event_type, title, weight
            from marts.patch_impact
            where app_id = %s and window_code = 'after_7'
              and (weight is null or weight >= %s)
            order by 1
        """, (app_id, min_weight))

    change_points = find_change_points(smoothed, sensitivity=sensitivity)

    cp_out = []
    for idx, score in change_points:
        day = smoothed[idx]["day"]
        day_date = datetime.fromisoformat(day).date()

        nearby = [
            e for e in events
            if abs((e["day"] - day_date).days) <= 3
        ]
        cp_out.append({
            "day": day,
            "score": round(score, 1),
            "events": [
                {"type": e["event_type"], "title": e["title"]}
                for e in nearby
            ],
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
        "change_points": cp_out,
    })


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)