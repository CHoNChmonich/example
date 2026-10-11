"""Сборка приложения FastAPI из готового контроллера."""

from collections.abc import MutableMapping
from typing import Any

from fastapi import FastAPI
from fastapi.telemetry import TelemetryConfig

from . import error_handlers
from .lifespan import Lifespan
from .v1 import HEALTHCHECK_PATH
from .v1 import Controller as V1Controller
from .v1 import create_router as create_v1_router


class App(FastAPI):
    """FastAPI с одним отличием проекта: без 422 в схеме.

    FastAPI дописывает 422 каждой ручке с валидацией, но ошибки разбора запроса адаптер
    отдаёт как 400 (он уже объявлен в картах ответов роутера), поэтому 422 и его модели
    из схемы убираются; ``super().openapi()`` кэширует схему, правка в ней сохраняется.
    """

    def openapi(self) -> dict[str, Any]:
        """Возвращает схему OpenAPI без ответов 422 и моделей ошибок валидации FastAPI.

        Returns:
            Кэшированная схема OpenAPI приложения.
        """
        schema = super().openapi()
        for path in schema["paths"].values():
            for operation in path.values():
                operation.get("responses", {}).pop("422", None)
        for model in ("HTTPValidationError", "ValidationError"):
            schema.get("components", {}).get("schemas", {}).pop(model, None)
        return schema


def create_app(
    *,
    v1_controller: V1Controller,
    v1_prefix: str = "/api/v1",
    lifespan: Lifespan | None = None,
) -> FastAPI:
    """Собирает приложение: маршруты v1, обработчики ошибок, lifespan, телеметрию.

    Трассировка — встроенная телеметрия FastAPI: серверный спан на запрос с именем по
    маршруту, продолжение входящего ``traceparent``, статус ERROR при необработанном
    исключении. Спан открывает ``FastAPI.__call__`` до входа в стек middleware, поэтому
    ``trace_id`` есть в каждой строке лога запроса, включая access-лог uvicorn; отдельного
    идентификатора запроса нет — корреляция клиента с сервером идёт через ``traceparent``.
    Служебные спаны операций, метрики, логи и автоконфигурация из ``OTEL_*`` выключены явно:
    экспорт задаёт только ``adapters.tracing``. ``healthcheck`` из трассы исключён по пути с
    учётом ``root_path``. Без глобального провайдера телеметрия неактивна.

    CORS не настраивается: у сервиса нет браузерного фронтенда.

    Args:
        v1_controller: Контроллер v1 с уже внедрёнными сервисами.
        v1_prefix: Префикс путей API v1.
        lifespan: Контекст жизненного цикла приложения (запуск и остановка адаптеров).

    Returns:
        Готовое к запуску приложение FastAPI.
    """
    healthcheck_path = f"{v1_prefix}{HEALTHCHECK_PATH}"
    telemetry: TelemetryConfig = {
        "tracing": True,
        "operation_spans": False,
        "metrics": False,
        "logs": False,
        "auto_configure": False,
        "exclude": lambda scope: _path_without_root(scope) == healthcheck_path,
    }
    app = App(
        title="Orders Service API",
        version="1.0.0",
        lifespan=lifespan,
        telemetry=telemetry,
        openapi_tags=[
            {"name": "v1: Customers"},
            {"name": "v1: Products"},
            {"name": "v1: Orders"},
        ],
    )
    error_handlers.register_error_handlers(app)
    app.include_router(create_v1_router(v1_controller, prefix=v1_prefix))
    return app


def _path_without_root(scope: MutableMapping[str, Any]) -> str:
    """Возвращает путь запроса без ``root_path``: по спецификации ASGI ``path`` его включает.

    Args:
        scope: ASGI scope HTTP-запроса.

    Returns:
        Путь относительно точки монтирования приложения.
    """
    path = str(scope.get("path", ""))
    return path.removeprefix(str(scope.get("root_path", "")).rstrip("/"))
