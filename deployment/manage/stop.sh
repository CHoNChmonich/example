#!/usr/bin/env bash
# Остановка контейнеров стенда без удаления (--dev — разработка, без флага — production).

set -e

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

set -a
source "$PWD"/.env
set +a

cd deployment

case "$1" in
--dev)
  echo "The development containers are stopping ..."
  docker compose -f docker-composes/dev/docker-compose.dev.yml stop
  ;;
*)
  echo "The production containers are stopping ..."
  docker compose -f docker-composes/prod/docker-compose.prod.yml stop
  ;;
esac
