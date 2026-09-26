#!/usr/bin/env bash
# Поднимает эту папку второй копией проекта рядом с первой: свои контейнеры, тома и порты, база - копия базы первой.
#
#   bash scripts/second-copy.sh ../steam-health                        # на той же машине: http://localhost:5001
#   bash scripts/second-copy.sh ../steam-health exp.steam-health.ru    # на сервере: ещё и поддомен через Caddy первой копии
#
# Сначала только проверяет и показывает, что будет сделано, и ждёт подтверждения.
# Первую копию читает (pg_dump); на сервере единственное изменение в ней - блок поддомена в конце её Caddyfile.
set -euo pipefail

SRC=$(cd "${1:?укажи папку первой копии, например ../steam-health}" && pwd)
DOMAIN=${2:-}
DST=$(pwd)
PG_PORT=${PG_PORT:-5434}
WEB_PORT=${WEB_PORT:-5001}
AIRFLOW_PORT=${AIRFLOW_PORT:-8081}

stop() { echo "стоп: $*" >&2; exit 1; }
ok() { echo "  ✓ $*"; }
human() { numfmt --to=iec "$1"; }
src() { (cd "$SRC" && docker compose "$@"); }
src_prod() { (cd "$SRC" && docker compose -f docker-compose.yml -f docker-compose.prod.yml "$@"); }
dst() { docker compose "$@"; }
sql() { local where=$1; shift; "$where" exec -T postgres sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -tAc \"$1\""; }

echo "== проверка"
[ "$SRC" != "$DST" ] || stop "запусти скрипт из папки второй копии, а не первой"
[ -f "$SRC/.env" ] || stop "в $SRC нет .env"
[ -f docker-compose.yml ] && [ -f docker-compose.exp.yml ] || stop "$DST - не папка проекта с нужной веткой"
[ ! -e .env ] || stop "в $DST уже есть .env - похоже, копия уже поднималась"
ok "первая копия: $SRC (ветка $(git -C "$SRC" branch --show-current))"
ok "вторая копия: $DST (ветка $(git branch --show-current))"

src ps --status running -q postgres | grep -q . || stop "в первой копии не запущен postgres"
reviews=$(sql src "select count(*) from core.fct_review")
db_size=$(sql src "select pg_database_size(current_database())")
ok "база первой копии: $(human "$db_size"), отзывов $reviews"

# копия базы плюс сборка образа; запас на индексы и временные файлы восстановления
disk=$(df -B1 --output=avail . | tail -1)
need=$((db_size * 2 + 3 * 1024 ** 3))
[ "$disk" -ge "$need" ] || stop "свободно $(human "$disk"), нужно хотя бы $(human "$need")"
ok "диск: свободно $(human "$disk"), нужно около $(human "$need")"
mem=$(awk '/MemAvailable/ {print $2 * 1024}' /proc/meminfo)
[ "$mem" -ge $((1024 ** 3)) ] && ok "память: доступно $(human "$mem")" \
  || echo "  ! память: доступно $(human "$mem") - вторая копия займёт ещё около 500 МБ, может быть тесно"

if command -v ss > /dev/null; then
  for port in "$PG_PORT" "$WEB_PORT"; do
    ! ss -ltn | grep -q ":$port " || stop "порт $port уже занят - задай другой: WEB_PORT=... PG_PORT=... bash scripts/second-copy.sh ..."
  done
  ok "порты $PG_PORT и $WEB_PORT свободны"
fi

if [ -n "$DOMAIN" ]; then
  caddy=$(src_prod ps --status running -q caddy)
  [ -n "$caddy" ] || stop "в первой копии не запущен caddy"
  network=$(docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}' "$caddy" | awk '{print $1}')
  ok "caddy первой копии запущен, сеть $network"
  ! grep -q "^$DOMAIN" "$SRC/Caddyfile" || stop "в $SRC/Caddyfile уже есть блок $DOMAIN"

  domain_ip=$(getent ahostsv4 "$DOMAIN" | awk 'NR == 1 {print $1}')
  [ -n "$domain_ip" ] || stop "$DOMAIN не находится в DNS - добавь запись A на IP сервера и подожди несколько минут"
  my_ips="$(hostname -I) $(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
  [[ " $my_ips " == *" $domain_ip "* ]] || stop "$DOMAIN указывает на $domain_ip, а у сервера $my_ips"
  ok "$DOMAIN указывает на этот сервер ($domain_ip)"
fi

echo
echo "== что будет сделано"
echo "  - .env второй копии: из первой, порты $PG_PORT/$WEB_PORT/$AIRFLOW_PORT, свой SECRET_KEY"
echo "  - своя база второй копии, в неё - копия базы первой ($(human "$db_size"))"
echo "  - сборка и запуск второй копии: миграции новой ветки, витрины, дашборд и воркер. Airflow не запускается"
[ -z "$DOMAIN" ] || echo "  - блок $DOMAIN в конце $SRC/Caddyfile (с резервной копией) и перечитывание caddy без перезапуска"
read -rp "Продолжить? [y/N] " answer
[ "$answer" = y ] || stop "отменено, ничего не изменено"

echo
echo "== .env"
cp "$SRC/.env" .env
sed -i '/^\(PG_PORT\|WEB_PORT\|WEB_HOST\|AIRFLOW_PORT\|SECRET_KEY\|COOKIE_SECURE\|COMPOSE_FILE\|MAIN_NETWORK\)=/d' .env
cat >> .env <<ENV

# --- вторая копия ---
PG_PORT=$PG_PORT
WEB_PORT=$WEB_PORT
AIRFLOW_PORT=$AIRFLOW_PORT
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
COOKIE_SECURE=$([ -n "$DOMAIN" ] && echo true || echo false)
ENV
[ -z "$DOMAIN" ] || printf 'COMPOSE_FILE=docker-compose.yml:docker-compose.exp.yml\nMAIN_NETWORK=%s\n' "$network" >> .env
ok "готов"

echo "== база"
dst up -d --wait postgres
[ "$(sql dst "select count(*) from information_schema.schemata where schema_name = 'core'")" = 0 ] \
  || stop "база второй копии не пустая - переносить поверх не буду"
src exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' \
  | dst exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' \
  || echo "  pg_restore вернул предупреждения - сверяю данные"
copied=$(sql dst "select count(*) from core.fct_review")
[ "$copied" = "$reviews" ] || stop "отзывов в копии $copied, в первой копии $reviews"
ok "отзывов перенесено: $copied"

echo "== запуск"
# образ собирается заранее: иначе compose пытается скачать его для web, worker и dbt из Docker Hub, где его нет
dst build
dst up -d
sql dst "drop table if exists marts.review_flat" > /dev/null
for _ in $(seq 30); do curl -fsS -o /dev/null "http://127.0.0.1:$WEB_PORT/" && break; sleep 2; done
curl -fsS -o /dev/null "http://127.0.0.1:$WEB_PORT/" || stop "дашборд не отвечает на порту $WEB_PORT - смотри docker compose logs web"
ok "дашборд отвечает: http://127.0.0.1:$WEB_PORT"

if [ -n "$DOMAIN" ]; then
  echo "== caddy"
  # дописывается, а не перезаписывается: caddy видит файл через монтирование, и новый файл вместо старого он бы не увидел
  backup="$SRC/Caddyfile.bak-$(date +%Y%m%d-%H%M%S)"
  cp "$SRC/Caddyfile" "$backup"
  printf '\n%s {\n    # вторая копия проекта: %s\n    reverse_proxy exp-web:5000\n}\n' "$DOMAIN" "$DST" >> "$SRC/Caddyfile"
  if ! src_prod exec -T caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile > /dev/null 2>&1; then
    cat "$backup" > "$SRC/Caddyfile"
    stop "caddy не принял новый Caddyfile - вернул прежний"
  fi
  src_prod exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
  ok "caddy перечитал настройки, резервная копия: $backup"
  for _ in $(seq 24); do curl -fsS -o /dev/null "https://$DOMAIN/" 2>/dev/null && break; sleep 5; done
  curl -fsS -o /dev/null "https://$DOMAIN/" && ok "https://$DOMAIN открывается" \
    || echo "  ! https://$DOMAIN пока не открывается - сертификат может выпускаться ещё пару минут"
fi

echo
echo "готово. Учётка для входа: docker compose exec web python users.py add <логин>"
