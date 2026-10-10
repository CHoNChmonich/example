"""Сборка приложения FastAPI из готового контроллера."""

from typing import Any

from fastapi import FastAPI
from starlette.types import ASGIApp

from . import error_handlers
from .lifespan import Lifespan
from .request_id import RequestIdMiddleware
from .v1 import Controller as V1Controller
from .v1 import create_router as create_v1_router


class App(FastAPI):
    """FastAPI с двумя отличиями проекта: без 422 в схеме и с request id снаружи стека.

    FastAPI дописывает 422 каждой ручке с валидацией, но ошибки разбора запроса адаптер
    отдаёт как 400 (он уже объявлен в картах ответов роутера), поэтому 422 и его модели
    из схемы убираются; ``super().openapi()`` кэширует схему, правка в ней сохраняется.
    ``RequestIdMiddleware`` оборачивает весь стек Starlette, а не добавляется через
    ``add_middleware``: иначе он оказался бы внутри ``ServerErrorMiddleware``, и ответ 500
    уходил бы без ``X-Request-ID``.
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

    def build_middleware_stack(self) -> ASGIApp:
        """Собирает стек middleware и оборачивает его корреляцией запросов снаружи.

        Returns:
            ASGI-приложение: ``RequestIdMiddleware`` поверх стандартного стека.
        """
        return RequestIdMiddleware(super().build_middleware_stack())


def create_app(
    *,
    v1_controller: V1Controller,
    v1_prefix: str = "/api/v1",
    lifespan: Lifespan | None = None,
) -> FastAPI:
    """Собирает приложение: маршруты v1, обработчики ошибок, lifespan.

    CORS не настраивается: у сервиса нет браузерного фронтенда.

    Args:
        v1_controller: Контроллер v1 с уже внедрёнными сервисами.
        v1_prefix: Префикс путей API v1.
        lifespan: Контекст жизненного цикла приложения (запуск и остановка адаптеров).

    Returns:
        Готовое к запуску приложение FastAPI.
    """
    app = App(
        title="Orders Service API",
        version="1.0.0",
        lifespan=lifespan,
        openapi_tags=[
            {"name": "v1: Customers"},
            {"name": "v1: Products"},
            {"name": "v1: Orders"},
        ],
    )
    error_handlers.register_error_handlers(app)
    app.include_router(create_v1_router(v1_controller, prefix=v1_prefix))
    return app
