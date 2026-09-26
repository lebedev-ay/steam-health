import os
import re
import uuid
from datetime import date, timedelta
from decimal import Decimal

from celery.result import AsyncResult
from flask import Flask, jsonify, render_template, request
from flask.json.provider import DefaultJSONProvider

from change_points import attach_events, build_events, build_series, find_change_points
from db import query
from tasks import (COLLECT_REVIEW_DAYS, COLLECT_REVIEW_PAGES, LOCK_KEY, LOCK_TTL,
                   celery_app, collect_game, redis_client)



class JSONProvider(DefaultJSONProvider):
    """Даты - ISO, как их ждёт JS; numeric из базы - обычные числа. По умолчанию Flask пишет даты в формате RFC 822."""

    @staticmethod
    def default(o):
        if isinstance(o, date):
            return o.isoformat()
        if isinstance(o, Decimal):
            return float(o)
        return DefaultJSONProvider.default(o)


app = Flask(__name__)
app.json = JSONProvider(app)

# защита /api/collect от случайного запроса, не от целенаправленного: токен уезжает в html страницы. Настоящая защита - basic auth на обратном прокси (Caddy)
COLLECT_TOKEN = os.getenv("COLLECT_TOKEN", "")

# какую игру открывать при заходе на дашборд; пусто - первая по алфавиту
DEFAULT_APP_ID = os.getenv("DEFAULT_APP_ID", "")

SMOOTHING = ("auto", "off", "7", "15", "29")
SENSITIVITY = ("2.5", "1.5", "1.0", "0.5")

# окна вокруг перелома - те же 7 дней, что в выводах (llm/verdict_check.py)
WINDOW = 7

# номера опор в тексте вывода нужны для проверки по уликам, читателю дашборда они ничего не говорят
SUPPORT_REFS_RE = re.compile(r"\s*\[\d+(?:\s*,\s*\d+)*\]")
APP_ID_RE = re.compile(r"store\.steampowered\.com/app/(\d+)")


def list_games():
    return query("select app_id, game_name, collection_status from marts.dim_game_current order by game_name")


def parse_app_id(raw):
    raw = str(raw or "").strip()
    m = APP_ID_RE.search(raw)
    if m:
        return int(m.group(1))
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


@app.route("/")
def index():
    return render_template("index.html", games=list_games(), collect_token=COLLECT_TOKEN,
                           default_app_id=DEFAULT_APP_ID, review_pages=COLLECT_REVIEW_PAGES,
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
    # nx=True - проверка и установка одной атомарной операцией: без него два одновременных запроса оба прошли бы дальше
    if not redis_client.set(LOCK_KEY, task_id, nx=True, ex=LOCK_TTL):
        return jsonify({"error": "сейчас идёт сбор другой игры", "busy_task_id": redis_client.get(LOCK_KEY)}), 409

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


@app.route("/api/game/<int:app_id>")
def game(app_id):
    """Всё для страницы игры одним ответом: шапка, ряд, события, переломы с выводами, темы отзывов и аудитория."""
    smoothing = request.args.get("smoothing", "auto")
    sensitivity = request.args.get("sensitivity", "1.5")
    if smoothing not in SMOOTHING or sensitivity not in SENSITIVITY:
        return jsonify({"error": f"smoothing - одно из {SMOOTHING}, sensitivity - одно из {SENSITIVITY}"}), 400

    info = query("""
        select app_id, game_name, developers, publishers, genres, release_date_parsed as release_date,
               metacritic_score, collection_status
        from marts.dim_game_current where app_id = %s
    """, (app_id,))
    if not info:
        return jsonify({"error": "такой игры в базе нет"}), 404

    smoothed, raw_daily, half, median = build_series(app_id, smoothing)
    out = {"game": info[0], "daily": smoothed, "window": half * 2 + 1, "median_volume": median,
           "events": [], "platform_events": [], "change_points": [], "change_points_note": None,
           "segments": segments(app_id), "aspects": aspects(app_id)}
    if not raw_daily:
        out["change_points_note"] = "по этой игре ещё нет собранных отзывов"
        return jsonify(out)

    events, platform_events = build_events(app_id, raw_daily)
    found, out["change_points_note"] = find_change_points(smoothed, sensitivity=float(sensitivity))
    verdicts = {v["change_date"]: verdict_view(v) for v in query("""
        select change_date, status, author, checks_passed, what_happened, what_players_say, excerpts
        from marts.change_point_verdict_current where app_id = %s
    """, (app_id,))}

    out["events"] = [{"day": e["day"], "type": e["event_type"], "title": e["title"], "weight": e["weight"]}
                     for e in events if e["shown"]]
    out["platform_events"] = [{"day": e["event_date"], "type": e["event_type"], "title": e["title"]}
                              for e in platform_events]
    out["change_points"] = [
        {**cp, **window_shares(raw_daily, cp["day"]), "verdict": verdicts.get(date.fromisoformat(cp["day"]))}
        for cp in attach_events(found, smoothed, events, platform_events)
    ]
    return jsonify(out)


def window_shares(raw_daily, day):
    """Доля положительных за 7 дней до перелома и 7 дней после, суммами по дням - как в уликах вывода."""
    at = date.fromisoformat(day)
    windows = {"before": (at - timedelta(days=WINDOW), at), "after": (at, at + timedelta(days=WINDOW))}
    out = {}
    for side, (lo, hi) in windows.items():
        rows = [r for r in raw_daily if lo <= r["day"] < hi]
        total = sum(r["total"] for r in rows)
        out[f"positive_{side}"] = round(100 * sum(r["positive"] for r in rows) / total) if total else None
    return out


def verdict_view(v):
    """Вывод для карточки перелома. Не прошедший проверку кодом - без текста: его писала модель, и проверка его не пропустила."""
    card = {"preliminary": v["status"] == "preliminary", "checked": v["checks_passed"]}
    if v["checks_passed"]:
        card["what_happened"] = SUPPORT_REFS_RE.sub("", v["what_happened"]).strip()
        if v["author"] == "model":
            card["what_players_say"] = SUPPORT_REFS_RE.sub("", v["what_players_say"] or "").strip()
            card["excerpts"] = [e["text"] for e in v["excerpts"]]
    return card


def segments(app_id):
    """{разрез: [{segment, reviews, positive}]} в естественном порядке; языки - по числу отзывов."""
    out = {}
    for r in query("""
        select dimension, segment, review_count as reviews, positive_count as positive
        from marts.review_segment where app_id = %s
        order by dimension, sort_order, review_count desc
    """, (app_id,)):
        out.setdefault(r.pop("dimension"), []).append(r)
    return out


def aspects(app_id):
    """Темы отзывов по LLM-разметке активной конфигурации; None - игра не размечалась.

    Доли считаются среди размеченных отзывов: разметка идёт выборкой с дневным лимитом, и в ней важны пропорции, а не число.
    """
    total = query("""
        select sum(d.labeled_count)::int as labeled, min(d.day) filter (where d.labeled_count > 0) as since,
               max(d.day) filter (where d.labeled_count > 0) as until
        from marts.review_labeling_daily d
        join marts.llm_config_active c on c.llm_config_sk = d.llm_config_sk
        where d.app_id = %s
    """, (app_id,))[0]
    if not total["labeled"]:
        return None

    items = query("""
        select a.category_id, a.aspect_id, sum(a.review_count)::int as mentions,
               sum(a.positive_count)::int as positive, sum(a.negative_count)::int as negative,
               sum(a.mixed_count)::int as mixed
        from marts.review_aspect_daily a
        join marts.llm_config_active c on c.llm_config_sk = a.llm_config_sk
        where a.app_id = %s and a.aspect_id not in ('overall_impression', 'other')
        group by a.category_id, a.aspect_id
        order by mentions desc
    """, (app_id,))

    # категории по месяцам: доля размеченных отзывов с критикой (минус или «±») - тепловая карта больных мест во времени
    months = query("""
        with labeled as (
            select date_trunc('month', d.day)::date as month, sum(d.labeled_count) as n
            from marts.review_labeling_daily d
            join marts.llm_config_active c on c.llm_config_sk = d.llm_config_sk
            where d.app_id = %(app)s
            group by 1
        )
        select date_trunc('month', a.day)::date as month, a.category_id,
               sum(a.negative_count + a.mixed_count)::int as critique, sum(a.positive_count)::int as praise,
               max(l.n)::int as labeled
        from marts.review_category_daily a
        join marts.llm_config_active c on c.llm_config_sk = a.llm_config_sk
        join labeled l on l.month = date_trunc('month', a.day)::date
        where a.app_id = %(app)s and a.category_id not in ('overall', 'other')
        group by 1, 2
        order by 1, 2
    """, {"app": app_id})

    return {**total, "items": items, "months": months}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
