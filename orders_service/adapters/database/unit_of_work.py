"""Unit of Work поверх ``AsyncSession``: три репозитория на одной сессии и одна транзакция."""

import socket
from types import TracebackType
from typing import Self

from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orders_service.application import errors, interfaces

from . import repositories

# Сбой сериализации, взаимная блокировка, отказ сервера принять соединение (лимит
# соединений, остановка или перезапуск): транзакцию можно повторить.
_TRANSIENT_SQLSTATES = frozenset({"40001", "40P01", "53300", "57P01", "57P02", "57P03"})


def _is_transient(exc: BaseException | None) -> bool:
    """Определяет, является ли исключение временным сбоем хранилища.

    Временными считаются: невозможность установить соединение (отказ или таймаут),
    неразрешимое имя хоста, исчерпание пула, разрыв соединения (диалект asyncpg не порождает
    ``OperationalError`` — обрыв приходит ``InterfaceError`` с флагом ``connection_invalidated``,
    «соединение признано мёртвым»), а также ошибки сервера с кодами из ``_TRANSIENT_SQLSTATES``.

    Args:
        exc: Исключение, вышедшее из тела транзакции, отката или commit; ``None``, если его нет.

    Returns:
        ``True``, если операцию имеет смысл повторить.
    """
    if isinstance(exc, ConnectionError | TimeoutError | socket.gaierror | PoolTimeoutError):
        return True
    if isinstance(exc, DBAPIError):
        if exc.connection_invalidated or isinstance(exc, OperationalError):
            return True
        return getattr(exc.orig, "sqlstate", None) in _TRANSIENT_SQLSTATES
    return False


class UnitOfWork(interfaces.UnitOfWork):
    """Транзакция SQLAlchemy над репозиториями клиентов, товаров и заказов.

    Паттерн: Adapter (GoF, в широком смысле) — приспосабливает ``AsyncSession`` к контракту
    порта ``interfaces.UnitOfWork``. Соединение берётся из пула при первом запросе
    (autobegin), поэтому вход в контекст ничего не делает; выход всегда откатывает
    незакоммиченное и закрывает сессию.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        customers: interfaces.CustomersRepo,
        products: interfaces.ProductsRepo,
        orders: interfaces.OrdersRepo,
    ) -> None:
        """Связывает сессию и репозитории, созданные на ней фабрикой.

        Args:
            session: Сессия транзакции.
            customers: Репозиторий клиентов на этой сессии.
            products: Репозиторий товаров на этой сессии.
            orders: Репозиторий заказов на этой сессии.
        """
        self._session = session
        self._customers = customers
        self._products = products
        self._orders = orders

    @property
    def customers(self) -> interfaces.CustomersRepo:
        """Репозиторий клиентов этой транзакции."""
        return self._customers

    @property
    def products(self) -> interfaces.ProductsRepo:
        """Репозиторий товаров этой транзакции."""
        return self._products

    @property
    def orders(self) -> interfaces.OrdersRepo:
        """Репозиторий заказов этой транзакции."""
        return self._orders

    async def __aenter__(self) -> Self:
        """Входит в контекст; транзакция начнётся при первом запросе.

        Returns:
            Сам Unit of Work.
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Откатывает незакоммиченное, закрывает сессию и переводит сбои хранилища.

        Откат после успешного commit холостой. Это единственное место перевода сбоев
        хранилища (включая ошибку commit) в ошибку ядра: исключение, поднятое здесь,
        заменяет исходное, сохраняя его как причину.

        Args:
            exc_type: Тип исключения, вышедшего из тела контекста, либо ``None``.
            exc: Само исключение либо ``None``.
            tb: Трассировка исключения либо ``None``.

        Raises:
            StorageUnavailable: Исходное исключение или сбой отката — временный сбой хранилища.
        """
        try:
            await self._session.rollback()
        except Exception as rollback_error:
            if _is_transient(rollback_error):
                raise errors.StorageUnavailable() from rollback_error
            raise
        finally:
            await self._session.close()
        if _is_transient(exc):
            raise errors.StorageUnavailable() from exc

    async def commit(self) -> None:
        """Фиксирует транзакцию; ошибка commit уходит в ``__aexit__`` и переводится там."""
        await self._session.commit()


class UnitOfWorkFactory(interfaces.UnitOfWorkFactory):
    """Паттерн: Abstract Factory (GoF) в вырожденной форме — одна операция ``create()``.

    Семейство объектов одной транзакции (сессия, три репозитория на ней, UoW) собирается
    внутри и отдаётся клиенту как единое целое.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Запоминает фабрику сессий движка.

        Args:
            session_factory: Фабрика сессий из ``Database.session_factory``.
        """
        self._session_factory = session_factory

    def create(self) -> UnitOfWork:
        """Создаёт сессию, три репозитория на ней и Unit of Work над ними.

        Returns:
            Ещё не начатый Unit of Work; транзакция начинается при первом запросе.
        """
        session = self._session_factory()
        return UnitOfWork(
            session,
            customers=repositories.CustomersRepo(session),
            products=repositories.ProductsRepo(session),
            orders=repositories.OrdersRepo(session),
        )
