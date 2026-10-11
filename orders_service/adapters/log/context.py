"""Контекст записей лога: идентификаторы трассы текущего спана."""

import logging

from opentelemetry import trace


class LogContextFilter(logging.Filter):
    """Дописывает в запись ``trace_id`` и ``span_id`` текущего спана (``-``, если спана нет).

    Идентификаторы читаются у фасада ``opentelemetry.trace``: без провайдера спан
    недействителен, и в записи остаётся ``-``. Фильтр вешается на хендлер, а не на логгер:
    так обогащаются и записи, пришедшие по ``propagate`` из чужих логгеров
    (``uvicorn.access``, ``sqlalchemy.engine``). Отдельного идентификатора запроса нет:
    запрос, транзакцию и SQL связывает ``trace_id``.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Добавляет атрибуты и пропускает запись.

        Args:
            record: Запись лога.

        Returns:
            Всегда ``True``: фильтр только обогащает.
        """
        span_context = trace.get_current_span().get_span_context()
        valid = span_context.is_valid
        record.__dict__["trace_id"] = trace.format_trace_id(span_context.trace_id) if valid else "-"
        record.__dict__["span_id"] = trace.format_span_id(span_context.span_id) if valid else "-"
        return True
