"""Учётки дашборда. Регистрации нет: учётку создаёт владелец руками.

    python users.py add <логин>        - завести, пароль спрашивается дважды и не попадает в историю shell
    python users.py passwd <логин>     - сменить пароль
    python users.py disable <логин>    - выключить: вход и открытые сессии перестают работать
    python users.py enable <логин>
    python users.py list

В docker: docker compose exec web python users.py add anna
"""

import argparse
import getpass

import psycopg
from werkzeug.security import generate_password_hash

from db import DSN

MIN_PASSWORD = 10


def ask_password():
    password = getpass.getpass("пароль: ")
    if len(password) < MIN_PASSWORD:
        raise SystemExit(f"пароль короче {MIN_PASSWORD} символов")
    if getpass.getpass("ещё раз: ") != password:
        raise SystemExit("пароли не совпали")
    return generate_password_hash(password)


def main():
    parser = argparse.ArgumentParser(description="Учётки дашборда")
    parser.add_argument("command", choices=["add", "passwd", "disable", "enable", "list"])
    parser.add_argument("login", nargs="?")
    args = parser.parse_args()
    if args.command != "list" and not args.login:
        parser.error("нужен логин")

    with psycopg.connect(DSN) as conn:
        if args.command == "list":
            for login, disabled, last in conn.execute(
                    "select login, disabled, last_login_at from app.web_user order by login"):
                print(f"{login:<24} {'выключен' if disabled else 'активен':<10} вход: {last or 'не было'}")
            return
        if args.command == "add":
            conn.execute("insert into app.web_user (login, password_hash) values (%s, %s)", (args.login, ask_password()))
        elif args.command == "passwd":
            changed = conn.execute("update app.web_user set password_hash = %s where login = %s",
                                   (ask_password(), args.login)).rowcount
        else:
            changed = conn.execute("update app.web_user set disabled = %s where login = %s",
                                   (args.command == "disable", args.login)).rowcount
        if args.command != "add" and not changed:
            raise SystemExit(f"нет пользователя {args.login}")
        print("готово")


if __name__ == "__main__":
    main()
