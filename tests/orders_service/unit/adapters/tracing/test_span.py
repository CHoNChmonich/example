import asyncio

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from orders_service.adapters import tracing
from orders_service.application import errors


# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
def _single(spans: InMemorySpanExporter) -> ReadableSpan:
    (span,) = spans.get_finished_spans()
    return span


def _exception_types(span: ReadableSpan) -> list[str]:
    types: list[str] = []
    for event in span.events:
        assert event.name == "exception"
        assert event.attributes is not None
        types.append(str(event.attributes["exception.type"]))
    return types


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestSpan:
    def test__success(self, spans: InMemorySpanExporter) -> None:
        # Call
        with tracing.span("work", {"key": "value"}) as current:
            inside = trace.get_current_span()

        # Assert: внутри блока спан текущий, после — завершён без статуса и снят с контекста
        assert inside is current
        span = _single(spans)
        assert span.name == "work"
        assert span.attributes is not None
        assert span.attributes["key"] == "value"
        assert span.status.status_code is StatusCode.UNSET
        assert span.events == ()
        assert not trace.get_current_span().get_span_context().is_valid

    def test__storage_unavailable_records_cause(self, spans: InMemorySpanExporter) -> None:
        # Setup
        cause = OSError("нет сети")

        # Call
        with pytest.raises(errors.StorageUnavailable) as excinfo:
            with tracing.span("work"):
                raise errors.StorageUnavailable() from cause

        # Assert: ERROR с исходным сбоем, а не с заменившей его ошибкой ядра
        assert excinfo.value.__cause__ is cause
        span = _single(spans)
        assert span.status.status_code is StatusCode.ERROR
        assert span.status.description == "OSError"
        assert _exception_types(span) == ["OSError"]

    def test__storage_unavailable_without_cause(self, spans: InMemorySpanExporter) -> None:
        # Call
        with pytest.raises(errors.StorageUnavailable):
            with tracing.span("work"):
                raise errors.StorageUnavailable()

        # Assert: без причины в событие идёт сама ошибка (тип — полным именем модуля)
        span = _single(spans)
        assert span.status.status_code is StatusCode.ERROR
        assert _exception_types(span) == ["orders_service.application.errors.StorageUnavailable"]

    def test__domain_error_is_not_a_span_error(self, spans: InMemorySpanExporter) -> None:
        # Call
        with pytest.raises(errors.CustomerNotFound):
            with tracing.span("work"):
                raise errors.CustomerNotFound(id=1)

        # Assert: ожидаемый исход сценария — код ошибки без ERROR и без события
        span = _single(spans)
        assert span.status.status_code is StatusCode.UNSET
        assert span.attributes is not None
        assert span.attributes[tracing.ERROR_CODE_ATTRIBUTE] == "customer_not_found"
        assert span.events == ()

    def test__unexpected_exception(self, spans: InMemorySpanExporter) -> None:
        # Setup
        error = ValueError("сбой")

        # Call
        with pytest.raises(ValueError) as excinfo:
            with tracing.span("work"):
                raise error

        # Assert: наружу тот же объект
        assert excinfo.value is error
        span = _single(spans)
        assert span.status.status_code is StatusCode.ERROR
        assert _exception_types(span) == ["ValueError"]
        assert not trace.get_current_span().get_span_context().is_valid

    def test__cancellation_leaves_status_unset(self, spans: InMemorySpanExporter) -> None:
        # Call
        with pytest.raises(asyncio.CancelledError):
            with tracing.span("work"):
                raise asyncio.CancelledError()

        # Assert: отмена — не сбой; спан всё равно завершён и снят с контекста
        span = _single(spans)
        assert span.status.status_code is StatusCode.UNSET
        assert span.events == ()
        assert not trace.get_current_span().get_span_context().is_valid
