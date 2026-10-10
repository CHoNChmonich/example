#!/usr/bin/env bash
# Прогон интеграционных тестов на отдельной БД (контейнер api_for_tests). В development
# падение тестов не роняет стенд (смотреть лог), в production контейнер завершается с ошибкой,
# и api не стартует.

set -e

if [[ $API_ENV == 'development' ]]; then
  # Выводим параметры подключения (без пароля)
  echo
  echo "TEST_POSTGRES_HOST: $TEST_POSTGRES_HOST"
  echo "TEST_POSTGRES_PORT: $TEST_POSTGRES_PORT"
  echo "TEST_POSTGRES_DB: $TEST_POSTGRES_DB"
  echo "TEST_POSTGRES_USER: $TEST_POSTGRES_USER"
fi

echo
echo "Waiting for database to start..."
timeout 30 bash -c \
  'while !</dev/tcp/$TEST_POSTGRES_HOST/$TEST_POSTGRES_PORT; do sleep 1; done'

echo
echo "Running integration tests..."
set +e
pytest -q ./tests/orders_service/integration
integration_test_status=$?
set -e

if [[ $integration_test_status -ne 0 ]]; then
  echo "One or more integration tests failed" >&2
  if [[ $API_ENV == 'production' ]]; then
    exit "$integration_test_status"
  fi
  exit 0
fi

echo "All tests passed successfully"
