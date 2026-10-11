"""Спан единицы работы: декоратор над любой реализацией порта ``interfaces.UnitOfWork``."""

from contextlib import AbstractContextManager
from types import TracebackType
from typing import Self

from opentelemetry import trace

from orders_service.application import interfaces

from .attributes import OUTCOME_ATTRIBUTE
from .spans import span


class TracedUnitOfWork(interfaces.UnitOfWork):
    """Единица работы под спаном ``unit_of_work``.

    Паттерн: Decorator (GoF) — реализует тот же порт, что и оборачиваемый Unit of Work,
    делегирует ему репозитории, вход, выход и commit, добавляя спан. Сервис работает с
    декоратором и не знает об обёртке; ``database.UnitOfWork`` о трассировке не знает.

    Спан открывается при входе и становится родителем спанов пула и SQL; атрибут
    ``OUTCOME_ATTRIBUTE`` говорит, зафиксирована транзакция (``committed``) или откачена
    (``rolled_back``). Исход по исключению ставит политика ``span``: ошибка ядра — ожидаемый
    исход без ERROR, ``StorageUnavailable`` — ERROR с исходной ошибкой хранилища. Спан живёт
    между ``__aenter__`` и ``__aexit__``, поэтому его контекстный менеджер хранится в объекте
    и закрывается явно; ``ExitStack`` для одного менеджера не нужен.
    """

    _scope: AbstractContextManager[trace.Span]
    _span: trace.Span

    def __init__(self, inner: interfaces.UnitOfWork) -> None:
        """Запоминает оборачиваемую единицу работы.

        Args:
            inner: Реализация порта, которой делегируется вся работа.
        """
        self._inner = inner

    @property
    def customers(self) -> interfaces.CustomersRepo:
        """Репозиторий клиентов оборачиваемой единицы работы."""
        return self._inner.customers

    @property
    def products(self) -> interfaces.ProductsRepo:
        """Репозиторий товаров оборачиваемой единицы работы."""
        return self._inner.products

    @property
    def orders(self) -> interfaces.OrdersRepo:
        """Репозиторий заказов оборачиваемой единицы работы."""
        return self._inner.orders

    async def __aenter__(self) -> Self:
        """Открывает спан, затем входит во внутреннюю единицу работы.

        Спан и его менеджер попадают в атрибуты только после успешного входа: иначе вложенный
        вход (внутренний UoW отвечает ``RuntimeError``) затёр бы состояние уже открытого
        объекта. При сбое входа спан закрывается с этим исключением.

        Returns:
            Сам декоратор — чтобы ``commit`` сервиса прошёл через него.
        """
        scope = span("unit_of_work", {OUTCOME_ATTRIBUTE: "rolled_back"})
        current = scope.__enter__()
        try:
            await self._inner.__aenter__()
        except BaseException as exc:
            scope.__exit__(type(exc), exc, exc.__traceback__)
            raise
        self._scope, self._span = scope, current
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Выходит из внутренней единицы работы и закрывает спан тем исключением, что уходит наружу.

        Внутренний ``__aexit__`` может заменить исключение тела (сбой хранилища →
        ``StorageUnavailable``) либо поднять своё (сбой отката) — тогда в спан идёт именно оно;
        иначе — исключение тела либо ничего. Менеджер ``span`` при повторном поднятии того же
        исключения возвращает ``False``, так что наружу уходит тот же объект.

        Args:
            exc_type: Тип исключения, вышедшего из тела контекста, либо ``None``.
            exc: Само исключение либо ``None``.
            tb: Трассировка исключения либо ``None``.
        """
        try:
            await self._inner.__aexit__(exc_type, exc, tb)
        except BaseException as replaced:
            self._scope.__exit__(type(replaced), replaced, replaced.__traceback__)
            raise
        else:
            self._scope.__exit__(exc_type, exc, tb)
        finally:
            del self._scope, self._span

    async def commit(self) -> None:
        """Фиксирует транзакцию через внутреннюю единицу работы и отмечает исход в спане."""
        await self._inner.commit()
        self._span.set_attribute(OUTCOME_ATTRIBUTE, "committed")
