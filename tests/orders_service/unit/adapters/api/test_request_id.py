import uuid

import pytest
from starlette.types import Message, Receive, Scope, Send

from orders_service.adapters import log
from orders_service.adapters.api.request_id import REQUEST_ID_HEADER, RequestIdMiddleware


# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
def _http_scope(headers: list[tuple[bytes, bytes]] | None = None) -> Scope:
    return {"type": "http", "method": "GET", "path": "/", "headers": headers or []}


async def _receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


class _Recorder:
    """Собирает отправленные ASGI-сообщения."""

    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def __call__(self, message: Message) -> None:
        self.messages.append(message)


class _App:
    """Приложение-заглушка: запоминает request_id во время вызова и отвечает 200."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0
        self.seen: str | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.calls += 1
        self.seen = log.request_id.get()
        if self.error is not None:
            raise self.error
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})


def _response_header(recorder: _Recorder) -> str:
    headers = dict(recorder.messages[0]["headers"])
    return str(headers[REQUEST_ID_HEADER.lower().encode()].decode())


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestRequestIdMiddleware:
    async def test__generates_uuid4(self) -> None:
        # Setup
        app, recorder = _App(), _Recorder()

        # Call
        await RequestIdMiddleware(app)(_http_scope(), _receive, recorder)

        # Assert
        value = _response_header(recorder)
        assert uuid.UUID(value).version == 4
        assert app.seen == value

    async def test__accepts_valid_header(self) -> None:
        # Setup
        app, recorder = _App(), _Recorder()
        scope = _http_scope([(b"x-request-id", b"trace-1.A_b")])

        # Call
        await RequestIdMiddleware(app)(scope, _receive, recorder)

        # Assert
        assert app.seen == "trace-1.A_b"
        assert _response_header(recorder) == "trace-1.A_b"

    @pytest.mark.parametrize("raw", [b"", b"a" * 65, b"two words", b"\xff\xfe", b"id;rm"])
    async def test__rejects_invalid_header(self, raw: bytes) -> None:
        # Setup
        app, recorder = _App(), _Recorder()
        scope = _http_scope([(b"x-request-id", raw)])

        # Call
        await RequestIdMiddleware(app)(scope, _receive, recorder)

        # Assert: недопустимое значение заменено сгенерированным
        value = _response_header(recorder)
        assert value != raw.decode("latin-1")
        assert uuid.UUID(value).version == 4

    async def test__context_reset_after_success(self) -> None:
        # Setup
        app, recorder = _App(), _Recorder()

        # Call
        await RequestIdMiddleware(app)(_http_scope(), _receive, recorder)

        # Assert
        assert app.seen is not None
        assert log.request_id.get() is None

    async def test__context_reset_after_exception(self) -> None:
        # Setup
        app, recorder = _App(error=RuntimeError("boom")), _Recorder()

        # Call and Assert
        with pytest.raises(RuntimeError):
            await RequestIdMiddleware(app)(_http_scope(), _receive, recorder)

        assert app.seen is not None
        assert log.request_id.get() is None

    async def test__non_http_scope_passthrough(self) -> None:
        # Setup
        app, recorder = _App(), _Recorder()

        # Call
        await RequestIdMiddleware(app)({"type": "lifespan"}, _receive, recorder)

        # Assert: приложение вызвано, контекст не ставился, заголовок не добавлен
        assert app.calls == 1
        assert app.seen is None
        assert recorder.messages[0]["headers"] == []
