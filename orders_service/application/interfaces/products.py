"""Порт персистентности товаров."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from orders_service.application import entities


class ProductsRepo(ABC):
    """Порт персистентности товаров."""

    @abstractmethod
    async def fetch_by_id(self, product_id: int) -> entities.Product | None:
        """Находит товар по идентификатору без блокировки.

        Args:
            product_id: Идентификатор товара.

        Returns:
            Товар или ``None``, если такого нет.
        """

    @abstractmethod
    async def fetch_by_ids(
        self, product_ids: Sequence[int], *, for_update: bool = False
    ) -> Sequence[entities.Product]:
        """Находит товары по списку идентификаторов.

        Остатки меняются только под блокировкой; порядок захвата задаёт сортировка по ``id``,
        одинаковая у всех транзакций.

        Args:
            product_ids: Идентификаторы товаров; отсутствующие молча пропускаются.
            for_update: Заблокировать строки до конца транзакции и вернуть их актуальное
                состояние, даже если товар уже читался в этой транзакции без блокировки.

        Returns:
            Найденные товары по возрастанию ``id``.
        """

    @abstractmethod
    async def add(self, product: entities.Product) -> entities.Product:
        """Сохраняет новый товар.

        Args:
            product: Товар без ``id``.

        Returns:
            Тот же объект с проставленным ``id``.
        """
