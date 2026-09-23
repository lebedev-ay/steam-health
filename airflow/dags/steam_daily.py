"""Ежедневный прогон: сбор из Steam, загрузка в core, сборка и проверка витрин."""

from datetime import timedelta

import pendulum
from airflow.sdk import DAG, Param
from airflow.providers.standard.operators.bash import BashOperator

COLLECTOR = "python /opt/project/collector"
DBT_BIN = "/opt/dbt-venv/bin/dbt"
DBT = f"DBT_BIN={DBT_BIN} python /opt/project/collector/run_dbt.py"
DBT_DIRS = "--project-dir /opt/project/dbt --profiles-dir /opt/project/dbt"

# сетевые задачи: Steam отваливается, повтор помогает
NET = {"retries": 2, "retry_delay": timedelta(minutes=5)}

DOC = """
### Ежедневный прогон steam-health

Собирает свежие отзывы и новости из Steam, догружает их в ядро и пересобирает витрины.
Идёт каждую ночь в 03:00 UTC. Обычный прогон занимает около полутора минут.

**Граф**

Отзывы и новости независимы, поэтому идут своими ветками. Витрины ждут обе:
упал сбор отзывов - патчи всё равно доедут до ядра, но `dbt_run` не запустится,
и дашборд покажет вчерашние данные целыми.

**Параметры**

| Параметр | По умолчанию | Что делает |
| --- | --- | --- |
| `app_id` | пусто | пусто - все игры из базы, иначе одна |
| `mode` | `incremental` | `full` - перекачать и перезагрузить всё заново |
| `review_pages` | 200 | предел страниц по 100 отзывов |
| `news_pages` | 10 | предел страниц новостей |
| `days` | пусто | глубина истории отзывов в днях |

**Что стоит знать**

- Загрузка отзывов инкрементальная: берётся только то, что новее последней
  загруженной порции сырья. Режим `full` перекачивает историю заново из Steam и
  перезагружает всё ядро: это десятки минут, зависит от скорости Steam, и предназначен
  он для восстановления, а не для регулярного прогона.
- Ретраи стоят только на сетевых задачах: Steam отваливается, повтор помогает.
  Если упала загрузка или dbt, повтор не поможет - причина не в сети.
- Запись в ядро и пересборка витрин идут под общим замком в PostgreSQL.
  Тот же замок берёт кнопка сбора на дашборде, поэтому два прогона не столкнутся.
- Полный прогон по всем играм сразу лучше не запускать: сбор упирается в скорость
  Steam и может не уложиться в `dagrun_timeout` в два часа. Надёжнее по одной игре.

Код: `airflow/dags/steam_daily.py`. Решения и отвергнутые варианты: `docs/decisions.md`, записи 038-042.
"""


with DAG(
    dag_id="steam_daily",
    schedule="0 3 * * *",
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=2),
    tags=["steam"],
    doc_md=DOC,
    params={
        "app_id": Param(None, type=["null", "integer"], description="пусто - все игры"),
        "mode": Param("incremental", enum=["incremental", "full"]),
        "review_pages": Param(200, type="integer"),
        "news_pages": Param(10, type="integer"),
        "days": Param(None, type=["null", "integer"], description="глубина истории отзывов"),
    },
):
    fetch_reviews = BashOperator(
        task_id="fetch_reviews",
        bash_command=(
            f"{COLLECTOR}/fetch_reviews.py {{{{ params.review_pages }}}}"
            " --mode {{ params.mode }}"
            "{% if params.app_id %} --app-id {{ params.app_id }}{% endif %}"
            "{% if params.days %} --days {{ params.days }}{% endif %}"
        ),
        **NET,
    )
    fetch_news = BashOperator(
        task_id="fetch_news",
        bash_command=(
            f"{COLLECTOR}/fetch_news.py {{{{ params.news_pages }}}}"
            " --mode {{ params.mode }}"
            "{% if params.app_id %} --app-id {{ params.app_id }}{% endif %}"
        ),
        **NET,
    )
    load_fct_review = BashOperator(
        task_id="load_fct_review",
        bash_command=(
            f"{COLLECTOR}/load_fct_review.py"
            "{% if params.app_id %} --app-id {{ params.app_id }}{% endif %}"
            "{% if params.mode == 'full' %} --full{% endif %}"
        ),
    )
    load_fct_patch = BashOperator(
        task_id="load_fct_patch",
        bash_command=(
            f"{COLLECTOR}/load_fct_patch.py"
            "{% if params.app_id %} --app-id {{ params.app_id }}{% endif %}"
        ),
    )
    dbt_run = BashOperator(task_id="dbt_run", bash_command=f"{DBT} run {DBT_DIRS}")
    dbt_test = BashOperator(task_id="dbt_test", bash_command=f"{DBT} test {DBT_DIRS}")

    fetch_reviews >> load_fct_review
    fetch_news >> load_fct_patch
    [load_fct_review, load_fct_patch] >> dbt_run >> dbt_test