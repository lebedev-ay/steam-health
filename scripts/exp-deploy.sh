#!/usr/bin/env bash
# Эксперимент рядом с рабочей копией одной командой: сам находит рабочую копию по запущенным контейнерам,
# клонирует ветку рядом с ней и передаёт дело scripts/second-copy.sh - тот всё проверит и спросит подтверждение.
#
#   bash exp-deploy.sh                          # поддомен exp.<домен рабочей копии из её Caddyfile>
#   bash exp-deploy.sh exp.example.ru           # свой поддомен
#   BRANCH=... bash exp-deploy.sh               # другая ветка
set -euo pipefail

REPO=https://github.com/lebedev-ay/steam-health.git
BRANCH=${BRANCH:-claude/kiss-refactor}
stop() { echo "стоп: $*" >&2; exit 1; }

# рабочая копия - папка, из которой compose запустил caddy; на машине без caddy - та, что запустила дашборд
find_dir() {
  docker ps --filter "label=com.docker.compose.service=$1" \
    --format '{{.Label "com.docker.compose.project.working_dir"}}' | sort -u
}
SRC=$(find_dir caddy)
MODE=сервер
[ -n "$SRC" ] || { SRC=$(find_dir web); MODE=локально; }
[ -n "$SRC" ] || stop "не нашёл запущенной рабочей копии: нет контейнеров caddy или web от docker compose"
[ "$(echo "$SRC" | wc -l)" = 1 ] || stop "нашёл несколько копий, выбери сам и запусти scripts/second-copy.sh вручную:
$SRC"
[ -f "$SRC/docker-compose.yml" ] && [ -f "$SRC/.env" ] || stop "в $SRC нет docker-compose.yml или .env"
git -C "$SRC" remote get-url origin | grep -q steam-health || stop "$SRC - не клон steam-health"
echo "рабочая копия ($MODE): $SRC, ветка $(git -C "$SRC" branch --show-current)"

DOMAIN=""
if [ "$MODE" = сервер ]; then
  main_domain=$(grep -oE '^[a-z0-9.-]+\.[a-z]+' "$SRC/Caddyfile" | head -1)
  DOMAIN=${1:-exp.$main_domain}
  [ -n "${1:-}" ] || [ -n "$main_domain" ] || stop "не нашёл домен в $SRC/Caddyfile - передай поддомен аргументом"
  echo "поддомен эксперимента: $DOMAIN"
fi

DST="$(dirname "$SRC")/steam-health-exp"
if [ -d "$DST" ]; then
  [ ! -e "$DST/.env" ] || stop "$DST уже поднят (там есть .env). Убрать: cd $DST && docker compose down -v, затем удалить папку"
  git -C "$DST" remote get-url origin | grep -q steam-health || stop "$DST существует и это не клон steam-health"
  git -C "$DST" fetch -q origin "$BRANCH"
else
  git clone -q "$REPO" "$DST"
fi
git -C "$DST" checkout -q "$BRANCH"
git -C "$DST" pull -q --ff-only origin "$BRANCH"
echo "эксперимент: $DST, ветка $BRANCH ($(git -C "$DST" log -1 --format=%h))"
echo

cd "$DST"
exec bash scripts/second-copy.sh "$SRC" $DOMAIN
