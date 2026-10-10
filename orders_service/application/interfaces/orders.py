"""Порт персистентности заказов."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from orders_service.application import dtos, entities


class OrdersRepo(ABC):
    """Порт персистентности заказов; заказ сохраняется вместе со строками."""

    @abstractmethod
    async def fetch_by_id(
        self, order_id: int, *, for_update: bool = False
    ) -> entities.Order | None:
        """Находит заказ со строками по идентификатору.

        Args:
            order_id: Идентификатор заказа.
            for_update: Заблокировать строку заказа до конца транзакции.

        Returns:
            Заказ с загруженными строками или ``None``, если такого нет.
        """

    @abstractmethod
    async def fetch_all(self, filter_params: dtos.FindOrders) -> Sequence[entities.Order]:
        """Находит заказы по фильтру.

        Args:
            filter_params: Клиент, статус, лимит и смещение выборки.

        Returns:
            Заказы по возрастанию ``id`` в пределах лимита и смещения.
        """

    @abstractmethod
    async def add(self, order: entities.Order) -> entities.Order:
        """Сохраняет новый заказ вместе со строками.

        Args:
            order: Заказ без ``id`` со строками без ``id``.

        Returns:
            Тот же объект с проставленными ``id`` заказа и строк.
        """
