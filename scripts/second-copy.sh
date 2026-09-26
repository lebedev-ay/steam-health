#!/usr/bin/env bash
# Поднимает эту папку второй копией проекта рядом с первой: свои контейнеры, тома и порты, база - копия базы первой.
# Запуск из папки новой копии: bash scripts/second-copy.sh ../steam-health
# Первую копию только читает (pg_dump). Прерывается на первой же проверке, которая не прошла.
set -euo pipefail

SRC=$(cd "${1:?укажи папку первой копии, например ../steam-health}" && pwd)
DST=$(pwd)
stop() { echo "стоп: $*" >&2; exit 1; }

[ "$SRC" != "$DST" ] || stop "запусти скрипт из папки второй копии, а не первой"
[ -f "$SRC/.env" ] || stop "в $SRC нет .env"
[ -f docker-compose.yml ] || stop "в $DST нет docker-compose.yml - это не папка проекта"
[ ! -e .env ] || stop "в $DST уже есть .env - похоже, копия уже поднималась"
(cd "$SRC" && docker compose ps --status running postgres -q | grep -q .) || stop "в $SRC не запущен postgres"

echo "первая копия: $SRC (только чтение)"
echo "вторая копия: $DST, ветка $(git branch --show-current)"

# .env первой копии плюс свои порты и ключ сессий
cp "$SRC/.env" .env
sed -i '/^\(PG_PORT\|WEB_PORT\|AIRFLOW_PORT\|SECRET_KEY\|COOKIE_SECURE\)=/d' .env
cat >> .env <<ENV

# --- вторая копия ---
PG_PORT=${PG_PORT:-5434}
WEB_PORT=${WEB_PORT:-5001}
AIRFLOW_PORT=${AIRFLOW_PORT:-8081}
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
COOKIE_SECURE=false
ENV

docker compose up -d --wait postgres
psql_dst() { docker compose exec -T postgres sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -tAc \"$1\""; }
psql_src() { (cd "$SRC" && docker compose exec -T postgres sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -tAc \"$1\""); }

[ "$(psql_dst "select count(*) from information_schema.schemata where schema_name = 'core'")" = 0 ] \
  || stop "база второй копии не пустая - переносить поверх не буду"

echo "копирую базу…"
(cd "$SRC" && docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"') \
  | docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' \
  || echo "pg_restore вернул предупреждения - сверяю данные"

src_n=$(psql_src "select count(*) from core.fct_review")
dst_n=$(psql_dst "select count(*) from core.fct_review")
[ "$src_n" = "$dst_n" ] || stop "отзывов в копии $dst_n, в оригинале $src_n"
echo "отзывов перенесено: $dst_n"

# миграции новой ветки, витрины, дашборд и воркер - уже на копии
docker compose up -d --build
psql_dst "drop table if exists marts.review_flat" > /dev/null

echo
echo "готово: http://localhost:$(grep '^WEB_PORT=' .env | cut -d= -f2)"
echo "учётка для входа: docker compose exec web python users.py add <логин>"
