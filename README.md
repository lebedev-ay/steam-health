# steam-health

Мониторинг здоровья игр в Steam: детект момента, когда патч
ломает или чинит игру.

## Что делает

Собирает отзывы и новости из Steam API, классифицирует события
(патчи, сезоны, маркетинг), считает сдвиг доли позитивных отзывов
в окнах вокруг события.

## Стек

Python, PostgreSQL 16, Docker, Plotly + Flask.
Дополнительно: Metabase, Power BI.

## Запуск

```bash
cp .env.example .env   # заполнить пароль
docker compose up -d
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python collector/migrate.py
```

## Структура

- `collector/` — сбор данных и загрузка в хранилище
- `db/migration/` — миграции схемы
- `web/` — дашборд на Flask + Plotly
- `docs/decisions.md` — журнал решений