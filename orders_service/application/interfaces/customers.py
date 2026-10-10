"""Порт персистентности клиентов."""

from abc import ABC, abstractmethod

from orders_service.application import entities


class CustomersRepo(ABC):
    """Порт персистентности клиентов."""

    @abstractmethod
    async def fetch_by_id(self, customer_id: int) -> entities.Customer | None:
        """Находит клиента по идентификатору.

        Args:
            customer_id: Идентификатор клиента.

        Returns:
            Клиент или ``None``, если такого нет.
        """

    @abstractmethod
    async def fetch_by_email(self, email: str) -> entities.Customer | None:
        """Находит клиента по email (точное совпадение).

        Args:
            email: Нормализованный email клиента.

        Returns:
            Клиент или ``None``, если такого нет.
        """

    @abstractmethod
    async def add(self, customer: entities.Customer) -> entities.Customer:
        """Сохраняет нового клиента.

        Args:
            customer: Клиент без ``id``.

        Returns:
            Тот же объект с проставленным ``id``.

        Raises:
            CustomerAlreadyExists: Email занят; гонку двух одновременных регистраций
                закрывает ограничение уникальности хранилища.
        """
