-- Пользователи дашборда: только они могут запускать сбор игры. Регистрации нет - учётки выдаются руками (web/users.py).
-- Отдельная схема app: это настройка приложения, а не данные хранилища, и dbt её не читает.
create schema if not exists app;

create table app.web_user (
    user_sk        serial primary key,
    login          text not null unique,
    password_hash  text not null,                 -- werkzeug.security, scrypt с солью; сам пароль нигде не хранится
    disabled       boolean not null default false, -- выключенный не войдёт, а уже открытая сессия перестаёт работать на следующем запросе
    created_at     timestamptz not null default now(),
    last_login_at  timestamptz
);
