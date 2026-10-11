"""Спан с политикой исхода проекта — единственное место, где исключение переводится в статус.

Контекстный менеджер ``span`` — идиома поверх ``tracer.start_as_current_span`` с отключённой
стандартной обработкой исключений: по умолчанию SDK помечает ERROR любое исключение, а для
сервиса ошибка ядра (``errors.Error``) — ожидаемый исход сценария, не сбой. Обёртки
(``TracedUnitOfWork``, ``Traced*``, ``TracedPool``) используют его и не дублируют правило;
SQL-слушатели ``database.spans`` — исключение: у них нет лексического блока, а любая ошибка SQL
инфраструктурная.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.trace import StatusCode
from opentelemetry.util.types import AttributeValue

from orders_service.application import errors

from .attributes import ERROR_CODE_ATTRIBUTE

tracer = trace.get_tracer(__name__)


@contextmanager
def span(name: str, attributes: Mapping[str, AttributeValue] | None = None) -> Iterator[trace.Span]:
    """Открывает спан как текущий и на выходе ставит исход по правилу проекта.

    Правило: ``StorageUnavailable`` — ERROR с исходным исключением из ``__cause__`` (сама
    ``StorageUnavailable`` — замена, причина информативнее); другая ошибка ядра — без ERROR,
    только атрибут ``ERROR_CODE_ATTRIBUTE``; прочее ``Exception`` — ERROR с событием;
    ``BaseException`` (отмена задачи) не перехватывается — спан завершается без статуса.
    Исключение всегда поднимается дальше.

    Args:
        name: Имя спана.
        attributes: Атрибуты при открытии; ключи с точками, поэтому словарь, а не kwargs.

    Yields:
        Открытый спан — для атрибутов, которые вызывающий ставит по ходу работы.
    """
    with tracer.start_as_current_span(
        name, attributes=attributes, record_exception=False, set_status_on_exception=False
    ) as current:
        try:
            yield current
        except errors.StorageUnavailable as exc:
            _fail(current, exc.__cause__ or exc)
            raise
        except errors.Error as exc:
            current.set_attribute(ERROR_CODE_ATTRIBUTE, exc.code)
            raise
        except Exception as exc:
            _fail(current, exc)
            raise


def _fail(current: trace.Span, exc: BaseException) -> None:
    """Записывает исключение в спан и ставит статус ERROR с именем его типа.

    Args:
        current: Спан, завершающийся сбоем.
        exc: Исключение, которое попадёт в событие спана.
    """
    current.record_exception(exc)
    current.set_status(StatusCode.ERROR, type(exc).__name__)
