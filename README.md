# steam-health

Аналитика здоровья игр в Steam: ищет момент, когда патч или новость
заметно сдвигают долю позитивных отзывов.

## Что делает

Собирает отзывы и новости 19 игр через Steam API, а также заметки
внешней игровой прессы — часть анонсов проходит мимо Steam-новостей.
Третий источник — события платформы целиком (распродажи, Steam
Awards, Next Fest) из служебного фида appid 753: они двигают
трафик сразу у многих игр, а не только у одной.
Классифицирует события (патчи, маркетинг, пресса) по заголовкам
через регулярки. Сглаживает долю позитивных отзывов окном, ширина
которого подстраивается под объём отзывов у конкретной игры, и ищет
на этой кривой точки перелома — дни, где настроение резко менялось.

![Дашборд](docs/img/dashboard.png)

## Как это работает

Три слоя. `raw` — сырой JSON от Steam API, как пришёл, только
дописывается. `core` — звезда: `dim_game` со SCD2-историей версий
игры и факты по патчам/отзывам. `marts` — витрины поверх core,
из них дашборд читает данные.

Подробная схема со всеми таблицами, диаграммами и тем, что
реально заполняется — в [docs/model.md](docs/model.md).

## Стек

Python, PostgreSQL 16, Docker, Flask + Plotly.

Отдельно: пробовал Metabase и Power BI, не подошли — подробности
в [docs/decisions.md](docs/decisions.md).

## Запуск

```bash
cp .env.example .env   # заполнить пароль
docker compose up -d
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python collector/migrate.py
python web/app.py       # http://localhost:5000
```

По умолчанию коллекторы `fetch_reviews.py`/`fetch_news.py` качают
только то, чего ещё нет (`--mode incremental`); `--mode full`
пересобирает всё заново. `--app-id <id>` ограничивает сбор одной
игрой — не обязательно из `games.txt`:

```bash
python collector/fetch_news.py --app-id 1245620
python collector/fetch_reviews.py 5 --app-id 1245620
python collector/fetch_reviews.py 5 --app-id 1245620 --mode full
```

## Фоновый сбор из дашборда

В шапке дашборда есть форма «ID игры или ссылка → Собрать»: она
ставит задачу в очередь (Celery + Redis) и опрашивает её статус,
не блокируя графики. Задача по шагам проверяет игру в Steam,
качает appdetails/новости/отзывы (`--mode` из формы) и грузит их
в core, в конце — `refresh materialized view concurrently` для
patch_impact (не блокирует чтение, но и не мгновенный).

Поднимается вместе со всем остальным:

```bash
docker compose up -d --build
```

Сервис `worker` — тот же образ, что `web`, командой
`celery -A tasks worker`. Без него `/api/collect` поставит задачу
в очередь, но она не выполнится, пока воркер не запущен.

## Структура

- `collector/` — сбор данных и загрузка в хранилище
- `db/migration/` — миграции схемы
- `web/` — дашборд на Flask + Plotly
- `docs/model.md` — модель данных: слои, схема core, витрины
- `docs/decisions.md` — журнал решений

## Решения и открытые вопросы

[docs/decisions.md](docs/decisions.md) — журнал решений в формате
ADR: что решили и почему. [docs/TODO.md](docs/TODO.md) — что не
сделано и что отложено осознанно.
