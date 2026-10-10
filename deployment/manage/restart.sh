#!/usr/bin/env bash
# Перезапуск стенда с пересборкой образов (--dev — разработка, без флага — production).

set -e

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

# Включаем автоматический экспорт переменных на время чтения .env
set -a
source "$PWD"/.env
set +a

cd deployment

case "$1" in
--dev)
  echo "The development containers are restarting ..."
  docker compose -f docker-composes/dev/docker-compose.dev.yml down
  docker compose -f docker-composes/dev/docker-compose.dev.yml up --build
  ;;
*)
  echo "The production containers are restarting ..."
  docker compose -f docker-composes/prod/docker-compose.prod.yml down
  docker compose -f docker-composes/prod/docker-compose.prod.yml up -d --build
  ;;
esac
