"""Учебный DAG: форма настоящего, задачи-пустышки."""

from datetime import timedelta

import pendulum
from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator

with DAG(
    dag_id="steam_daily_demo",
    schedule="0 3 * * *",
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["demo"],
):
    fetch_reviews = BashOperator(
        task_id="fetch_reviews",
        bash_command="echo 'собираю отзывы' && sleep 10",
        retries=2,
        retry_delay=timedelta(seconds=30),
    )
    fetch_news = BashOperator(
        task_id="fetch_news",
        bash_command="echo 'собираю новости' && sleep 5",
        retries=2,
        retry_delay=timedelta(seconds=30),
    )
    load_core = BashOperator(
        task_id="load_core",
        bash_command="echo 'гружу в core' && sleep 5",
    )
    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command="echo 'dbt run' && sleep 5",
    )
    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command="echo 'dbt test' && sleep 3",
    )

    [fetch_reviews, fetch_news] >> load_core >> dbt_run >> dbt_test