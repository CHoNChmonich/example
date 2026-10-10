#!/usr/bin/env bash
# Сборка и запуск стенда: с флагом --dev — разработка (compose в foreground, логи в консоли,
# Ctrl+C останавливает), без флага — production (в фоне).

set -e

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

# Экспорт корневого .env: compose подставляет ${...} из окружения, а .env лежит не рядом
# с compose-файлом
set -a
source "$PWD"/.env
set +a

cd deployment

case "$1" in
--dev)
  echo "The development containers are running ..."
  docker compose -f docker-composes/dev/docker-compose.dev.yml up --build
  ;;
*)
  echo "The production containers are running ..."
  docker compose -f docker-composes/prod/docker-compose.prod.yml up -d --build
  ;;
esac
