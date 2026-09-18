# Слой поверх slim-образа Airflow: зависимости коллектора и отдельное окружение для dbt.
# Код проекта сюда НЕ копируется - он монтируется томами, как у web и worker.
FROM apache/airflow:slim-3.3.1-python3.12

USER root

# git нужен не сборке, а dbt: он ищет его в PATH
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# dbt живёт в отдельном venv: его зависимости пересекаются с зависимостями Airflow.
# Вызывать будем по полному пути /opt/dbt-venv/bin/dbt
RUN python -m venv /opt/dbt-venv \
    && /opt/dbt-venv/bin/pip install --no-cache-dir \
        dbt-core==1.12.3 \
        dbt-postgres==1.11.0

USER airflow

# то, что есть в обычном образе, но не в slim: драйвер метабазы и наши провайдеры.
# Ставим с файлом ограничений Airflow, чтобы не сломать зависимости ядра
RUN pip install --no-cache-dir \
        "apache-airflow[postgres]==3.3.1" \
        apache-airflow-providers-standard \
        apache-airflow-providers-fab \
        --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.3.1/constraints-3.12.txt"

# библиотеки коллектора - без ограничений Airflow, это независимые пакеты
RUN pip install --no-cache-dir \
        requests==2.32.3 \
        "psycopg[binary]==3.3.4"