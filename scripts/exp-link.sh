#!/usr/bin/env bash
# Связывает дашборд второй копии с caddy первой через отдельную сеть steam-exp-proxy, где дашборд виден только как exp-web.
# Общая сеть с первой копией не годится: там сервисы второй копии откликались бы на те же имена web, postgres, redis,
# и caddy первой копии отправлял бы часть запросов во вторую.
# Связь теряется, когда пересоздаётся контейнер caddy или дашборда: тогда поддомен отвечает 502, а скрипт запускается снова.
# Запуск из папки второй копии: bash scripts/exp-link.sh
set -euo pipefail

NET=steam-exp-proxy
stop() { echo "стоп: $*" >&2; exit 1; }
attached() { docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}' "$1" | grep -qw "$NET"; }

web=$(docker compose ps -q web)
[ -n "$web" ] || stop "дашборд этой копии не запущен"
caddy=$(docker ps -q --filter label=com.docker.compose.service=caddy)
[ "$(echo "$caddy" | grep -c .)" = 1 ] || stop "ожидался ровно один запущенный caddy"

docker network inspect "$NET" > /dev/null 2>&1 || docker network create "$NET" > /dev/null
attached "$web" || docker network connect --alias exp-web "$NET" "$web"
attached "$caddy" || docker network connect "$NET" "$caddy"
echo "  ✓ дашборд и caddy связаны через $NET"
