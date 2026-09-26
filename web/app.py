import re
import uuid
from datetime import date, timedelta
from decimal import Decimal

from celery.result import AsyncResult
from flask import Flask, jsonify, render_template, request
from flask.json.provider import DefaultJSONProvider
from werkzeug.middleware.proxy_fix import ProxyFix

import auth
import game
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
# дашборд живёт за Caddy: адрес клиента для ограничения попыток входа и схема https - из заголовков прокси
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
auth.init(app)

SMOOTHING = ("auto", "off", "7", "15", "29")
SENSITIVITY = ("2.5", "1.5", "1.0", "0.5")
APP_ID_RE = re.compile(r"store\.steampowered\.com/app/(\d+)")


def parse_app_id(raw):
    raw = str(raw or "").strip()
    m = APP_ID_RE.search(raw)
    if m:
        return int(m.group(1))
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


def parse_day(raw, default):
    try:
        return date.fromisoformat(raw) if raw else default
    except ValueError:
        return None


@app.route("/")
def index():
    return render_template("index.html", review_pages=COLLECT_REVIEW_PAGES, review_days=COLLECT_REVIEW_DAYS)


@app.route("/api/games")
def games():
    return jsonify(game.games_overview())


@app.route("/api/game/<int:app_id>")
def game_page(app_id):
    """Всё для страницы игры одним ответом: шапка, ряд, события, переломы с выводами, темы, аудитория, сводки."""
    smoothing = request.args.get("smoothing", "auto")
    sensitivity = request.args.get("sensitivity", "1.5")
    if smoothing not in SMOOTHING or sensitivity not in SENSITIVITY:
        return jsonify({"error": f"smoothing - одно из {SMOOTHING}, sensitivity - одно из {SENSITIVITY}"}), 400
    page = game.game_page(app_id, smoothing, float(sensitivity))
    return jsonify(page) if page else (jsonify({"error": "такой игры в базе нет"}), 404)


@app.route("/api/game/<int:app_id>/aspect/<aspect_id>")
def aspect(app_id, aspect_id):
    return jsonify(game.aspect_detail(app_id, aspect_id))


@app.route("/api/game/<int:app_id>/reviews")
def reviews(app_id):
    """Отзывы с текстом за период: ?since=&until= (until не входит), vote=up|down, lang=, sort=helpful|recent, offset="""
    until = parse_day(request.args.get("until"), date.today() + timedelta(days=1))
    since = parse_day(request.args.get("since"), (until or date.today()) - timedelta(days=30))
    vote = request.args.get("vote") or None
    sort = request.args.get("sort", "helpful")
    try:
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        offset = None
    if since is None or until is None or offset is None or vote not in (None, "up", "down") or sort not in ("helpful", "recent"):
        return jsonify({"error": "since/until - даты YYYY-MM-DD, vote - up или down, sort - helpful или recent"}), 400
    return jsonify(game.reviews(app_id, since, until, vote, request.args.get("lang") or None, sort, offset))


@app.route("/api/me")
def me():
    return jsonify({"login": auth.current_user(), "enabled": bool(auth.SECRET_KEY)})


@app.route("/api/login", methods=["POST"])
def login():
    return auth.login(redis_client)


@app.route("/api/logout", methods=["POST"])
def logout():
    return auth.logout()


@app.route("/api/collect", methods=["POST"])
@auth.login_required
def start_collect():
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
@auth.login_required
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
