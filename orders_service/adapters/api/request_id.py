"""Корреляция запросов: ``X-Request-ID`` принимается или генерируется, попадает в лог и ответ."""

import re
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from orders_service.adapters import log

REQUEST_ID_HEADER = "X-Request-ID"
_HEADER_NAME = REQUEST_ID_HEADER.lower().encode()
# Входящий заголовок — недоверенный ввод: в лог и ответ попадает только короткий безопасный id.
_VALID_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


class RequestIdMiddleware:
    """Чистый ASGI-middleware: ставит ``log.request_id`` на время запроса и возвращает заголовок.

    Стоит снаружи всего стека Starlette (см. ``App.build_middleware_stack``), поэтому id
    видят и обработчики ошибок, и ответ 500 от ``ServerErrorMiddleware``. Не-HTTP scope
    (``lifespan``) пропускается без изменений. Contextvar сбрасывается в ``finally``;
    трассировку необработанного исключения uvicorn пишет уже после этого — без id, рядом
    со строкой access-лога, где id есть.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Оборачивает ASGI-приложение.

        Args:
            app: Следующее приложение в цепочке.
        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Обрабатывает один ASGI-вызов.

        Args:
            scope: ASGI scope.
            receive: Канал входящих сообщений.
            send: Канал исходящих сообщений.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        value = _incoming_request_id(scope) or str(uuid4())
        token = log.request_id.set(value)

        async def send_with_header(message: Message) -> None:
            """Добавляет заголовок с id в начало ответа и передаёт сообщение дальше.

            Args:
                message: Исходящее ASGI-сообщение.
            """
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((_HEADER_NAME, value.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            log.request_id.reset(token)


def _incoming_request_id(scope: Scope) -> str | None:
    """Достаёт допустимый ``X-Request-ID`` из заголовков запроса.

    Args:
        scope: ASGI scope HTTP-запроса.

    Returns:
        Значение заголовка, если он есть и проходит проверку формата; иначе ``None``.
    """
    for name, raw in scope.get("headers", []):
        if name == _HEADER_NAME:
            value = raw.decode("latin-1")
            return value if _VALID_ID.fullmatch(value) else None
    return None
