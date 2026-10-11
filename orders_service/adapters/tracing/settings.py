"""Настройки трассировки."""

import socket
from importlib.metadata import version
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from orders_service import ENV_FILE

type Exporter = Literal["none", "console", "otlp"]


def _package_version() -> str:
    """Версия установленного пакета сервиса — значение ``service.version`` по умолчанию.

    Returns:
        Версия из метаданных дистрибутива ``orders-service`` (``pyproject.toml``).
    """
    return version("orders-service")


class Settings(BaseSettings):
    """Трассировка OpenTelemetry: переменные окружения и ``.env`` в корне проекта.

    Стандартные переменные ``OTEL_*`` поверхностью конфигурации не являются: явные значения
    отсюда перекрывают то, что SDK читает из окружения сам.

    Attributes:
        TRACING_EXPORTER: Куда уходят спаны: ``none`` — никуда (спаны строятся и отбрасываются,
            идентификаторы в логах есть), ``console`` — в stdout, ``otlp`` — OTLP/HTTP на
            ``TRACING_OTLP_ENDPOINT``.
        TRACING_OTLP_ENDPOINT: Полный URL ресурса traces коллектора.
        TRACING_SAMPLE_RATIO: Доля записываемых корневых трасс от 0 до 1; решение родителя
            (входящий ``traceparent``) уважается независимо от доли. У незаписанных трасс
            ``trace_id`` в логах остаётся.
        TRACING_SERVICE_NAME: Имя сервиса в ресурсе спанов (``service.name``).
        TRACING_SERVICE_VERSION: Версия сервиса (``service.version``); по умолчанию — версия
            установленного пакета.
        TRACING_ENVIRONMENT: Окружение развёртывания (``deployment.environment``):
            ``development``, ``staging``, ``production`` и т. п.
        TRACING_SERVICE_INSTANCE_ID: Идентификатор экземпляра (``service.instance.id``); по
            умолчанию — имя хоста, в контейнере это идентификатор контейнера или имя пода.
    """

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    TRACING_EXPORTER: Exporter = "none"
    TRACING_OTLP_ENDPOINT: str = "http://localhost:4318/v1/traces"
    TRACING_SAMPLE_RATIO: float = Field(default=1.0, ge=0.0, le=1.0)
    TRACING_SERVICE_NAME: str = "orders-service"
    TRACING_SERVICE_VERSION: str = Field(default_factory=_package_version)
    TRACING_ENVIRONMENT: str = "development"
    TRACING_SERVICE_INSTANCE_ID: str = Field(default_factory=socket.gethostname)
