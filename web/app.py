import re
from datetime import datetime

import psycopg
from psycopg.rows import dict_row
from flask import Flask, render_template, jsonify, request
from celery.result import AsyncResult

from tasks import celery_app, collect_game
# db.py лежит в collector/ — путь туда добавляет в sys.path сам
# tasks.py при своём импорте (см. web/tasks.py), поэтому этот
# import обязан идти после import tasks, а не в общей группе выше
from db import DSN

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


# см. docs/decisions.md — почему перелом бывает необъяснимым
SIGNIFICANT_WEIGHT = 2
SIGNIFICANT_TYPES = {"patch", "season_start", "expansion"}

# для таблицы влияния событий (см. decisions.md): меньше — доля
# позитива скачет от случайности объёма, а не от самого события
EVENT_IMPACT_MIN_REVIEWS = 30
# 10 п.п. был по распределению верным, но завышенным по смыслу:
# таблица усредняет неделю до/после, детект переломов смотрит
# на конкретный день — резкий скачок за 2-3 дня в недельном окне
# растворяется. На Cyberpunk 2077 (1091500) события с полными
# окнами и объёмом есть, максимальный недельный сдвиг — 4.8 п.п.
# при базовом уровне ~94%; порог 10 отсекал их все. Устойчивый
# недельный сдвиг такого масштаба (Marathon, 78% → 31%) — редкость,
# а не норма. На 1565 событиях порог >= 3 п.п. оставляет 801,
# >= 5 — 520, >= 10 — 185 (~10 на игру из 19, слишком строго)
EVENT_IMPACT_MIN_SHIFT = 3
EVENT_IMPACT_LIMIT = 20


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
    try:
        app_id = int(request.args.get("app_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "app_id должен быть числом"}), 400

    smoothing = request.args.get("smoothing", "auto")
    if smoothing not in ("off", "auto"):
        try:
            int(smoothing)
        except ValueError:
            return jsonify({"error": "smoothing — off, auto или число дней"}), 400

    try:
        min_weight = float(request.args.get("min_weight", 0))
    except ValueError:
        return jsonify({"error": "min_weight должен быть числом"}), 400

    try:
        sensitivity = float(request.args.get("sensitivity", 1.5))
    except ValueError:
        return jsonify({"error": "sensitivity должен быть числом"}), 400

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

    # события для объяснения переломов: без фильтра по типу — тип
    # можно скрыть на графике (например, блоги), но перелом всё равно
    # нужно объяснить, если такое событие рядом есть
    cp_events = query("""
        select distinct published_date as day, event_type, title, weight
        from marts.patch_impact
        where app_id = %s and window_code = 'after_7'
          and (weight is null or weight >= %s)
        order by 1
    """, (app_id, min_weight))

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
        # без фильтра типов это тот же запрос, что и cp_events выше —
        # не гонять его второй раз
        events = cp_events

    # платформенные события (распродажи, Steam Awards, Next Fest) —
    # общие для всех игр, не зависят от app_id. Дата приблизительная,
    # см. docs/decisions.md
    platform_events = query("""
        select event_date, event_type, title
        from core.dim_platform_event
        where event_date >= %s and event_date <= %s
        order by event_date
    """, (raw_daily[0]["day"], raw_daily[-1]["day"]))

    change_points = find_change_points(smoothed, sensitivity=sensitivity)

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
                {"type": e["event_type"], "title": e["title"]}
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
    })


@app.route("/api/event_impact")
def event_impact():
    try:
        app_id = int(request.args.get("app_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "app_id должен быть числом"}), 400

    # before_7 и after_7 одного patch_sk — окна должны быть полными
    # (иначе сравниваем целое с обрезанным, запись 009) и не мельче
    # EVENT_IMPACT_MIN_REVIEWS отзывов в каждом
    rows = query("""
        select
            b.patch_sk, b.published_date, b.event_type, b.title,
            b.review_count as before_count,
            b.positive_count as before_positive,
            a.review_count as after_count,
            a.positive_count as after_positive
        from marts.patch_impact b
        join marts.patch_impact a on a.patch_sk = b.patch_sk
        where b.app_id = %s
          and b.window_code = 'before_7' and b.window_complete
          and a.window_code = 'after_7' and a.window_complete
          and b.review_count >= %s and a.review_count >= %s
    """, (app_id, EVENT_IMPACT_MIN_REVIEWS, EVENT_IMPACT_MIN_REVIEWS))

    events = []
    for r in rows:
        # доли — деление сумм в конце, а не усреднение готовых
        # процентов (принцип из decisions.md, запись 008)
        before_pct = 100 * r["before_positive"] / r["before_count"]
        after_pct = 100 * r["after_positive"] / r["after_count"]
        shift = after_pct - before_pct

        if abs(shift) < EVENT_IMPACT_MIN_SHIFT:
            continue

        events.append({
            "day": r["published_date"].isoformat(),
            "type": r["event_type"],
            "title": r["title"],
            "before_pct": round(before_pct, 1),
            "after_pct": round(after_pct, 1),
            "shift": round(shift, 1),
            "before_count": r["before_count"],
            "before_positive": r["before_positive"],
            "after_count": r["after_count"],
            "after_positive": r["after_positive"],
        })

    events.sort(key=lambda e: abs(e["shift"]), reverse=True)

    return jsonify({"events": events[:EVENT_IMPACT_LIMIT]})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)