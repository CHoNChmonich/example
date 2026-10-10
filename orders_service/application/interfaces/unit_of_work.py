"""Порты Unit of Work и его фабрики."""

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self

from .customers import CustomersRepo
from .orders import OrdersRepo
from .products import ProductsRepo


class UnitOfWork(ABC):
    """Одна транзакция над несколькими репозиториями (паттерн Unit of Work, PoEAA).

    Репозитории разделяют одну сессию хранилища и живут ровно одну транзакцию.
    Сервисы не вызывают ``commit()`` сами — это делает обёртка ``@transactional`` при
    нормальном выходе из метода. ``__aexit__`` реализации обязан откатить всё
    незакоммиченное, закрыть сессию и перевести инфраструктурные сбои хранилища
    в ``errors.StorageUnavailable``.

    Сущности, полученные из репозиториев, действительны только внутри контекста: откат
    при выходе сбрасывает их состояние. Поэтому сервисы собирают DTO до выхода из метода
    и наружу отдают именно их.

    Репозитории объявлены абстрактными свойствами, а не аннотациями: только так
    ``Mock(spec=UnitOfWork)`` в тестах видит эти атрибуты.
    """

    @property
    @abstractmethod
    def customers(self) -> CustomersRepo:
        """Репозиторий клиентов этой транзакции."""

    @property
    @abstractmethod
    def products(self) -> ProductsRepo:
        """Репозиторий товаров этой транзакции."""

    @property
    @abstractmethod
    def orders(self) -> OrdersRepo:
        """Репозиторий заказов этой транзакции."""

    @abstractmethod
    async def __aenter__(self) -> Self:
        """Начинает единицу работы; соединение может открываться лениво, при первом запросе.

        Returns:
            Сам Unit of Work.
        """

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Завершает единицу работы: откатывает незакоммиченное и освобождает ресурсы.

        Args:
            exc_type: Тип исключения, вышедшего из тела контекста, либо ``None``.
            exc: Само исключение либо ``None``.
            tb: Трассировка исключения либо ``None``.

        Raises:
            StorageUnavailable: Исходное исключение или сбой отката — временный сбой хранилища.
        """

    @abstractmethod
    async def commit(self) -> None:
        """Фиксирует транзакцию; вызывается только обёрткой ``@transactional``."""


class UnitOfWorkFactory(ABC):
    """Паттерн: Abstract Factory (GoF) в вырожденной форме — одна операция создания.

    Семейство объектов одной транзакции (сессия, репозитории на ней, UoW над ними)
    собирается внутри и отдаётся клиенту целиком как UoW. Подмена реализации
    (SQLAlchemy ↔ мок в тестах) подменяет всё семейство. Фабрика, а не один UoW на сервис:
    сервисы — синглтоны, запросы конкурентны, поэтому UoW создаётся заново на каждый вызов.
    """

    @abstractmethod
    def create(self) -> UnitOfWork:
        """Создаёт новый Unit of Work с собственными репозиториями.

        Returns:
            Ещё не начатый Unit of Work; транзакция начинается при входе в контекст.
        """
