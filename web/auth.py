"""Вход для тех, кому выданы учётки: только они запускают сбор игры. Чтение дашборда открыто всем.

Сессия - подписанная кука Flask (HttpOnly, SameSite=Lax, Secure на проде). Пароли - хэши werkzeug со солью.
Подделку запроса с чужого сайта закрывают SameSite, JSON-тело (форма с чужого сайта его не пошлёт без CORS) и сверка Origin.
Перебор паролей - не больше LOGIN_ATTEMPTS попыток с одного адреса за LOGIN_WINDOW секунд.
"""

import os
from datetime import timedelta
from functools import wraps
from urllib.parse import urlparse

from flask import jsonify, request, session
from werkzeug.security import check_password_hash

from db import execute, query

SECRET_KEY = os.getenv("SECRET_KEY", "")
LOGIN_ATTEMPTS = 10
LOGIN_WINDOW = 15 * 60
# хэш для несуществующего логина: проверка занимает то же время, и по времени ответа не узнать, есть ли такой пользователь
DUMMY_HASH = "scrypt:32768:8:1$dummysaltdummys$" + "0" * 128


def init(app):
    # без ключа входа нет: подписать сессию нечем, и сбор просто недоступен
    app.secret_key = SECRET_KEY or None
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # локально дашборд открывают по http, и кука с Secure туда не придёт; на проде за Caddy всегда https
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "1") != "0",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    )


def current_user():
    """Логин вошедшего или None. Учётка перечитывается из базы: выключенная перестаёт работать сразу."""
    if not SECRET_KEY or "user_sk" not in session:
        return None
    rows = query("select login from app.web_user where user_sk = %s and not disabled", (session["user_sk"],))
    if not rows:
        session.clear()
        return None
    return rows[0]["login"]


def same_origin():
    origin = request.headers.get("Origin") or request.headers.get("Referer")
    return origin is not None and urlparse(origin).netloc == request.host


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if request.method != "GET" and not same_origin():
            return jsonify({"error": "запрос не с этого сайта"}), 403
        if current_user() is None:
            return jsonify({"error": "нужно войти"}), 401
        return view(*args, **kwargs)
    return wrapped


def login(redis_client):
    """POST /api/login: {login, password} -> сессия. Ответ одинаковый для неверного логина и неверного пароля."""
    if not SECRET_KEY:
        return jsonify({"error": "вход не настроен: нет SECRET_KEY"}), 503
    if not same_origin():
        return jsonify({"error": "запрос не с этого сайта"}), 403

    key = f"login:{request.remote_addr}"
    attempts = redis_client.incr(key)
    if attempts == 1:
        redis_client.expire(key, LOGIN_WINDOW)
    if attempts > LOGIN_ATTEMPTS:
        return jsonify({"error": "слишком много попыток, попробуйте через 15 минут"}), 429

    body = request.get_json(silent=True) or {}
    name, password = str(body.get("login") or "").strip(), str(body.get("password") or "")
    rows = query("select user_sk, password_hash from app.web_user where login = %s and not disabled", (name,))
    stored = rows[0]["password_hash"] if rows else DUMMY_HASH
    if not (check_password_hash(stored, password) and rows):
        return jsonify({"error": "неверный логин или пароль"}), 401

    redis_client.delete(key)
    # новая сессия на входе: идентификатор, подсунутый до входа, не должен пережить его
    session.clear()
    session.permanent = True
    session["user_sk"] = rows[0]["user_sk"]
    execute("update app.web_user set last_login_at = now() where user_sk = %s", (rows[0]["user_sk"],))
    return jsonify({"login": name})


def logout():
    # без ключа сессии нет вовсе, а менять её Flask в таком случае не даёт
    if SECRET_KEY:
        session.clear()
    return jsonify({"login": None})
