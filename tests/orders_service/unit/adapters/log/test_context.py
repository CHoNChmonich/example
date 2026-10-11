import logging
import re

from opentelemetry.sdk.trace import TracerProvider

from orders_service.adapters import log


# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
def _record() -> logging.LogRecord:
    return logging.LogRecord("x", logging.INFO, __file__, 1, "сообщение", None, None)


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestLogContextFilter:
    def test__dashes_without_span(self) -> None:
        # Setup
        record = _record()

        # Call
        passed = log.LogContextFilter().filter(record)

        # Assert
        assert passed is True
        assert record.__dict__["trace_id"] == "-"
        assert record.__dict__["span_id"] == "-"

    def test__trace_ids_from_current_span(self) -> None:
        # Setup: локальный провайдер — текущий спан живёт в contextvars, глобальный не нужен
        record = _record()
        tracer = TracerProvider().get_tracer("test")

        # Call
        with tracer.start_as_current_span("span") as span:
            passed = log.LogContextFilter().filter(record)

        # Assert
        assert passed is True
        assert record.__dict__["trace_id"] == f"{span.get_span_context().trace_id:032x}"
        assert re.fullmatch(r"[0-9a-f]{32}", record.__dict__["trace_id"])
        assert re.fullmatch(r"[0-9a-f]{16}", record.__dict__["span_id"])
