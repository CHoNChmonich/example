#!/usr/bin/env bash
# Запуск API: миграции → uvicorn.
# Параметры из окружения: API_ENV (задаёт стадия Dockerfile), API_WORKER_COUNT, LOG_LEVEL,
# ADDITIONAL_API_ARGS.

set -e

/usr/bin/entrypoint_alembic.sh

: "${API_ENV:=production}"
: "${API_WORKER_COUNT:=4}"
: "${LOG_LEVEL:=INFO}"
: "${ADDITIONAL_API_ARGS:=}"

echo
echo "API_ENV: ${API_ENV}"
echo "API_WORKER_COUNT: ${API_WORKER_COUNT}"
echo "LOG_LEVEL: ${LOG_LEVEL}"
echo "ADDITIONAL_API_ARGS: ${ADDITIONAL_API_ARGS}"
echo

# exec — uvicorn становится PID 1 и получает SIGTERM от docker stop напрямую;
# --proxy-headers — адрес клиента и схема берутся из заголовков nginx
# shellcheck disable=SC2086
exec uvicorn orders_service.launchers.api:app \
  --host 0.0.0.0 --port 8000 \
  --workers "${API_WORKER_COUNT}" \
  --log-level "${LOG_LEVEL,,}" \
  --proxy-headers --forwarded-allow-ips '*' \
  ${ADDITIONAL_API_ARGS}
