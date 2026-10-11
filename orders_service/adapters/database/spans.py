"""Спаны SQLAlchemy: запросы и взятие соединения из пула, по одному набору на движок.

Готовый инструментор OpenTelemetry не поддерживает SQLAlchemy 2.1 и патчит библиотеку
глобально; здесь то же самое делается явно и только для переданного движка. Спан запроса
начинается перед выполнением курсора и завершается после него либо при ошибке — у слушателей
событий нет лексического блока, поэтому политика ``tracing.span`` им недоступна, а любая
ошибка SQL инфраструктурная. Спан взятия соединения даёт ``TracedPool``. Родителем становится
текущий спан (единица работы или запрос): contextvars доходят до greenlet SQLAlchemy.
Пакет ``tracing`` импортируется как библиотека; обратных импортов нет.
"""

from opentelemetry import trace
from opentelemetry.trace import SpanKind, StatusCode
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.engine.interfaces import ExceptionContext
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import AsyncAdaptedQueuePool, PoolProxiedConnection

from orders_service.adapters.tracing import (
    POOL_CHECKED_IN_ATTRIBUTE,
    POOL_CHECKED_OUT_ATTRIBUTE,
    POOL_SIZE_ATTRIBUTE,
    span,
)

tracer = trace.get_tracer(__name__)

# Ключ открытого спана в conn.info: выполнения на одном соединении идут последовательно.
_SPAN_KEY = "orders_service.span"


class TracedPool(AsyncAdaptedQueuePool):
    """Пул соединений со спаном ``pool.connect`` на каждое взятие соединения.

    Расширение наследованием, не Decorator: у пула нет порта, класс передаётся движку через
    ``poolclass``. ``Pool.connect()`` вызывает ``Engine.raw_connection()`` при первом запросе
    транзакции; ожидание свободного слота, проверка ``pool_pre_ping`` и установка нового
    физического соединения происходят внутри, поэтому длительность спана — время, которое
    транзакция ждала соединение. Повторные запросы той же транзакции берут соединение из
    сессии и спана не дают. Атрибуты — состояние пула до взятия.
    """

    def connect(self) -> PoolProxiedConnection:
        """Берёт соединение из пула под спаном.

        Returns:
            Соединение пула; его ``close()`` возвращает соединение в пул.
        """
        attributes = {
            POOL_SIZE_ATTRIBUTE: self.size(),
            POOL_CHECKED_IN_ATTRIBUTE: self.checkedin(),
            POOL_CHECKED_OUT_ATTRIBUTE: self.checkedout(),
        }
        with span("pool.connect", attributes):
            return super().connect()


def instrument(engine: AsyncEngine) -> None:
    """Вешает слушатели выполнения запросов на синхронную часть движка.

    Args:
        engine: Движок, запросы которого попадут в трассу.
    """
    event.listen(engine.sync_engine, "before_cursor_execute", _start_span)
    event.listen(engine.sync_engine, "after_cursor_execute", _end_span)
    event.listen(engine.sync_engine, "handle_error", _fail_span)


def _start_span(
    conn: Connection,
    cursor: object,
    statement: str,
    parameters: object,
    context: object,
    executemany: bool,
) -> None:
    """Открывает спан запроса: имя — SQL-операция, текст запроса — в атрибутах, без параметров.

    Операция — первое слово текста: для запросов SQLAlchemy это ``SELECT``/``INSERT``/…, для
    сырого SQL с комментарием или CTE — то, что стоит первым. Имена атрибутов — старые
    семантические конвенции OpenTelemetry (``db.system``, ``db.operation``, ``db.statement``).

    Args:
        conn: Соединение, на котором выполняется запрос.
        cursor: Курсор DBAPI; не используется.
        statement: Текст запроса.
        parameters: Параметры запроса; в спан не попадают.
        context: Контекст выполнения; не используется.
        executemany: Пакетное ли выполнение; не используется.
    """
    operation = statement.split(maxsplit=1)[0].upper() if statement else "SQL"
    conn.info[_SPAN_KEY] = tracer.start_span(
        operation,
        kind=SpanKind.CLIENT,
        attributes={
            "db.system": "postgresql",
            "db.operation": operation,
            "db.statement": statement,
        },
    )


def _end_span(
    conn: Connection,
    cursor: object,
    statement: str,
    parameters: object,
    context: object,
    executemany: bool,
) -> None:
    """Завершает спан успешно выполненного запроса.

    Args:
        conn: Соединение, на котором выполнялся запрос.
        cursor: Курсор DBAPI; не используется.
        statement: Текст запроса; не используется.
        parameters: Параметры запроса; не используются.
        context: Контекст выполнения; не используется.
        executemany: Пакетное ли выполнение; не используется.
    """
    query_span = conn.info.pop(_SPAN_KEY, None)
    if query_span is not None:
        query_span.end()


def _fail_span(exception_context: ExceptionContext) -> None:
    """Завершает спан запроса, упавшего с ошибкой: записывает исключение и статус.

    Args:
        exception_context: Контекст ошибки SQLAlchemy с соединением и исходным исключением.
    """
    connection = exception_context.connection
    query_span = connection.info.pop(_SPAN_KEY, None) if connection is not None else None
    if query_span is None:
        return
    error = exception_context.original_exception
    query_span.record_exception(error)
    query_span.set_status(StatusCode.ERROR, type(error).__name__)
    query_span.end()
