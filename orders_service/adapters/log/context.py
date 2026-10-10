"""Контекст записей лога: идентификатор запроса, общий для всех записей одной единицы работы."""

import logging
from contextvars import ContextVar

# Ставит входящий адаптер на время запроса, читает RequestIdFilter; вне запроса — None.
request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    """Дописывает в запись ``request_id`` из контекста (``-``, если контекста нет).

    Вешается на хендлер, а не на логгер: так обогащаются и записи, пришедшие по ``propagate``
    из чужих логгеров (``uvicorn.access``, ``sqlalchemy.engine``).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Добавляет атрибут и пропускает запись.

        Args:
            record: Запись лога.

        Returns:
            Всегда ``True``: фильтр только обогащает.
        """
        record.__dict__["request_id"] = request_id.get() or "-"
        return True
