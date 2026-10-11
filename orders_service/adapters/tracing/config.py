"""Провайдер трассировки: ресурс, сэмплер, процессор и экспортёр по настройкам."""

import asyncio
from typing import assert_never

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import (
    DEPLOYMENT_ENVIRONMENT,
    SERVICE_INSTANCE_ID,
    SERVICE_NAME,
    SERVICE_VERSION,
    Resource,
)
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.sdk.trace.sampling import ParentBased, Sampler, TraceIdRatioBased

from .settings import Settings


def _one_line(span: ReadableSpan) -> str:
    """Форматирует спан для консоли одной JSON-строкой.

    Args:
        span: Завершённый спан.

    Returns:
        JSON спана и перевод строки.
    """
    return str(span.to_json(indent=None)) + "\n"


def _make_processor(settings: Settings) -> SpanProcessor | None:
    """Выбирает процессор и экспортёр спанов по ``TRACING_EXPORTER``.

    Консоль получает синхронный процессор: спан печатается сразу при завершении, одной
    JSON-строкой, и не ломает поток записей лога в формате ``json``. OTLP — пакетный,
    записи уходят в фоне; без доступного коллектора экспорт повторяет попытки и при
    остановке задерживает процесс на несколько секунд.

    Args:
        settings: Настройки трассировки.

    Returns:
        Процессор с экспортёром внутри либо ``None`` для ``none``.
    """
    exporter = settings.TRACING_EXPORTER
    match exporter:
        case "none":
            return None
        case "console":
            return SimpleSpanProcessor(ConsoleSpanExporter(formatter=_one_line))
        case "otlp":
            return BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.TRACING_OTLP_ENDPOINT))
        case _:
            assert_never(exporter)


def _make_sampler(settings: Settings) -> Sampler:
    """Собирает сэмплер: доля корневых трасс по ``TRACING_SAMPLE_RATIO``, решение родителя — выше.

    ``ParentBased``: у спана с родителем решение наследуется (входящий ``traceparent`` с
    флагом sampled записывается целиком, без флага — не записывается), и только корневой спан
    решает сам по доле ``TraceIdRatioBased``. Решение принимается по ``trace_id``, поэтому
    трасса либо записана на всех сервисах, либо нигде.

    Args:
        settings: Настройки трассировки.

    Returns:
        Сэмплер для провайдера.
    """
    return ParentBased(TraceIdRatioBased(settings.TRACING_SAMPLE_RATIO))


def _make_resource(settings: Settings) -> Resource:
    """Собирает ресурс: кто создал спаны — сервис, версия, окружение, экземпляр.

    Без версии и окружения трассы разных релизов и стендов в одном бэкенде неразличимы;
    идентификатор экземпляра отличает реплики одного сервиса.

    Args:
        settings: Настройки трассировки.

    Returns:
        Ресурс с атрибутами семантических конвенций OpenTelemetry.
    """
    return Resource.create(
        {
            SERVICE_NAME: settings.TRACING_SERVICE_NAME,
            SERVICE_VERSION: settings.TRACING_SERVICE_VERSION,
            DEPLOYMENT_ENVIRONMENT: settings.TRACING_ENVIRONMENT,
            SERVICE_INSTANCE_ID: settings.TRACING_SERVICE_INSTANCE_ID,
        }
    )


def _make_provider(settings: Settings) -> TracerProvider:
    """Собирает провайдер: ресурс, сэмплер и процессор, если экспорт включён.

    Args:
        settings: Настройки трассировки.

    Returns:
        Провайдер, ещё не установленный глобально.
    """
    provider = TracerProvider(resource=_make_resource(settings), sampler=_make_sampler(settings))
    processor = _make_processor(settings)
    if processor is not None:
        provider.add_span_processor(processor)
    return provider


def configure(settings: Settings) -> TracerProvider:
    """Устанавливает провайдер глобально для процесса.

    OpenTelemetry принимает провайдер один раз: повторный вызов игнорируется с
    предупреждением в логе, поэтому composition root вызывает его единожды.

    Args:
        settings: Настройки трассировки.

    Returns:
        Установленный провайдер — для остановки при завершении приложения.
    """
    provider = _make_provider(settings)
    trace.set_tracer_provider(provider)
    return provider


async def shutdown(provider: TracerProvider) -> None:
    """Останавливает провайдер: досылает накопленные спаны и освобождает экспортёр.

    Экспорт блокирующий (у OTLP — HTTP с повторами), поэтому уводится в поток, чтобы не
    держать event loop во время остановки приложения.

    Args:
        provider: Провайдер, созданный ``configure``.
    """
    await asyncio.to_thread(provider.shutdown)
