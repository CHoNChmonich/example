import logging

from orders_service.adapters import log


# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
def _record() -> logging.LogRecord:
    return logging.LogRecord("x", logging.INFO, __file__, 1, "сообщение", None, None)


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestRequestIdFilter:
    def test__request_id_from_context(self) -> None:
        # Setup
        record = _record()
        token = log.request_id.set("abc")

        # Call
        try:
            passed = log.RequestIdFilter().filter(record)
        finally:
            log.request_id.reset(token)

        # Assert
        assert passed is True
        assert record.__dict__["request_id"] == "abc"

    def test__dash_without_context(self) -> None:
        # Setup
        record = _record()

        # Call
        passed = log.RequestIdFilter().filter(record)

        # Assert
        assert passed is True
        assert record.__dict__["request_id"] == "-"
