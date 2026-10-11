#!/usr/bin/env bash
# Прогон интеграционных тестов на отдельной БД (контейнер api_for_tests dev-стенда).
# Падение тестов не роняет стенд — смотреть лог контейнера.

set -e

# Выводим параметры подключения (без пароля)
echo
echo "TEST_POSTGRES_HOST: $TEST_POSTGRES_HOST"
echo "TEST_POSTGRES_PORT: $TEST_POSTGRES_PORT"
echo "TEST_POSTGRES_DB: $TEST_POSTGRES_DB"
echo "TEST_POSTGRES_USER: $TEST_POSTGRES_USER"

echo
echo "Waiting for database to start..."
timeout 30 bash -c \
  'while !</dev/tcp/$TEST_POSTGRES_HOST/$TEST_POSTGRES_PORT; do sleep 1; done'

echo
echo "Running integration tests..."
if ! pytest -q ./tests/orders_service/integration; then
  echo "One or more integration tests failed" >&2
  exit 0
fi

echo "All tests passed successfully"
