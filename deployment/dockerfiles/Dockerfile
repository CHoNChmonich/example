# Стадии по образцу hex_arch/deployment/backend/Dockerfile, на uv вместо Poetry:
#   base → dependency-installer → builder (wheel проекта) → tests / development / production
# Контекст сборки — корень проекта (см. docker-composes/*/docker-compose.*.yml и .dockerignore).

# ====================================================
# Базовый образ: общие переменные среды, пользователь приложения, entrypoint-скрипты
FROM python:3.12-slim AS base

ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PYTHONDONTWRITEBYTECODE=1 \
    # uv: файлы копировать (кэш на другом слое), байт-код компилировать при установке,
    # Python брать из образа, кэш в слоях не хранить
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1 \
    # Окружение проекта — на PATH во всех стадиях
    PATH="/app/.venv/bin:$PATH"

RUN groupadd --system app \
 && useradd --system --gid app --no-create-home --shell /usr/sbin/nologin app

# Скопировать и сделать исполняемыми скрипты запуска контейнеров
COPY deployment/entrypoints/entrypoint_*.sh /usr/bin/
RUN chmod +x /usr/bin/entrypoint_*.sh

WORKDIR /app


# ====================================================
# Зависимости приложения без dev-группы и без самого проекта: слой живёт, пока не меняются
# pyproject.toml и uv.lock
FROM base AS dependency-installer

COPY --from=ghcr.io/astral-sh/uv:0.7.15 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev


# ====================================================
# Сборка проекта: wheel собирается и ставится в то же окружение (не editable) — в production
# уходит только .venv с установленным пакетом, без исходников
FROM dependency-installer AS builder

COPY orders_service ./orders_service
RUN uv sync --frozen --no-dev --no-editable


# ====================================================
# Тесты: dev-зависимости, исходники и тесты. Unit-тесты выполняются при сборке образа,
# интеграционные — при запуске контейнера (entrypoint_tests.sh, отдельная БД)
FROM dependency-installer AS tests

COPY orders_service ./orders_service
COPY tests ./tests
RUN uv sync --frozen \
 && pytest -q tests/orders_service/unit

ENTRYPOINT ["entrypoint_tests.sh"]


# ====================================================
# Разработка: образ тестов (dev-зависимости, исходники); API применяет миграции и стартует
# через entrypoint_api.sh
FROM tests AS development

ENV API_ENV=development

ENTRYPOINT ["entrypoint_api.sh"]


# ====================================================
# Production: только окружение с установленным пакетом — без uv, исходников и тестов; non-root
FROM base AS production

ENV API_ENV=production
COPY --from=builder --chown=app:app /app/.venv /app/.venv
USER app

ENTRYPOINT ["entrypoint_api.sh"]
