FROM python:3.12-slim

WORKDIR /app

# git — не для сборки, а для dbt: dbt debug и dbt deps ищут git
# в PATH независимо от того, использует ли сам проект пакеты dbt
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY web/ .
COPY collector/ collector/
COPY dbt/ dbt/

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "app:app"]
