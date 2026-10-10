#!/usr/bin/env bash
# Удаление контейнеров, сети и собранных образов стенда (--dev — разработка, без флага —
# production). Volumes с данными Postgres и pgAdmin остаются: с ними — `docker compose … down -v`.

set -e

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

set -a
source "$PWD"/.env
set +a

cd deployment

case "$1" in
--dev)
  echo "The development containers and images are removing ..."
  docker compose -f docker-composes/dev/docker-compose.dev.yml down --rmi local
  ;;
*)
  echo "The production containers and images are removing ..."
  docker compose -f docker-composes/prod/docker-compose.prod.yml down --rmi local
  ;;
esac
