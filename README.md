# steam-health

Аналитика здоровья игр в Steam: ищет момент, когда патч или новость
заметно сдвигают долю позитивных отзывов.

## Что делает

Собирает отзывы и новости 19 игр через Steam API, а также заметки
внешней игровой прессы — часть анонсов проходит мимо Steam-новостей.
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

## Сбор онлайна по расписанию

Steam API отдаёт только текущее число игроков, истории нет —
её накапливает `collector/fetch_player_count.py`, снимая по одной
точке за запуск. Чем раньше поставить на расписание, тем длиннее
история. Пример cron на каждые 30 минут:

```
*/30 * * * * cd /path/to/steam-health && .venv/bin/python collector/fetch_player_count.py >> /tmp/player_count.log 2>&1
```

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
