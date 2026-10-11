"""Провайдер трассировки для всего прогона.

OpenTelemetry принимает глобальный провайдер один раз на процесс. Этот conftest загружается
раньше любых тестов и фикстур, поэтому провайдер с экспортёром в памяти ставится здесь, на
уровне модуля; более поздние попытки (``tracing.configure`` при импорте composition root
в ``unit/launchers/test_api.py``) SDK игнорирует с предупреждением в логе — это ожидаемо.
"""

from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

_exporter = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(_exporter))
trace.set_tracer_provider(_provider)


@pytest.fixture(scope="function")
def spans() -> Iterator[InMemorySpanExporter]:
    # Экспортёр общий на процесс: чистится до и после теста. Autouse-фикстуры с запросами к БД
    # (fill_db) отрабатывают раньше, поэтому тесты чистят его ещё раз перед вызовом
    _exporter.clear()
    yield _exporter
    _exporter.clear()
