"""Входящий порт сценариев заказа."""

from abc import ABC, abstractmethod

from orders_service.application import dtos


class Order(ABC):
    """Сценарии заказа — входящий порт.

    Контроллеры и декораторы зависят от этого порта, а не от ``services.Order``: так
    сценарий можно обернуть или подменить без правки сервиса.
    Контракт методов (аргументы, результат, ошибки) описан здесь; реализация описывает
    только особенности исполнения.
    """

    @abstractmethod
    async def place(self, new_order_info: dtos.NewOrderInfo) -> dtos.Order:
        """Оформляет заказ: проверяет клиента и товары, резервирует остатки, применяет скидку.

        Args:
            new_order_info: Клиент и строки заказа.

        Returns:
            Сохранённый заказ со строками, скидкой и суммой к оплате.

        Raises:
            CustomerNotFound: Клиента с таким идентификатором нет.
            ProductNotFound: Какого-то из товаров нет; называется первый отсутствующий
                в порядке строк заказа.
            InsufficientStock: Остатка товара не хватает; ничего не сохраняется.
            StorageUnavailable: Временный сбой хранилища.
        """

    @abstractmethod
    async def get(self, order_id: int) -> dtos.Order:
        """Возвращает заказ по идентификатору.

        Args:
            order_id: Идентификатор заказа.

        Returns:
            Найденный заказ со строками.

        Raises:
            OrderNotFound: Заказа с таким идентификатором нет.
            StorageUnavailable: Временный сбой хранилища.
        """

    @abstractmethod
    async def find(self, filter_params: dtos.FindOrders) -> list[dtos.Order]:
        """Находит заказы по фильтру.

        Args:
            filter_params: Клиент, статус, лимит и смещение выборки.

        Returns:
            Заказы по возрастанию идентификатора; пустой список, если ничего не найдено.

        Raises:
            StorageUnavailable: Временный сбой хранилища.
        """

    @abstractmethod
    async def pay(self, order_id: int) -> dtos.Order:
        """Оплачивает заказ.

        Args:
            order_id: Идентификатор заказа.

        Returns:
            Заказ в статусе ``paid``.

        Raises:
            OrderNotFound: Заказа с таким идентификатором нет.
            OrderTransitionNotAllowed: Заказ уже оплачен или отменён.
            StorageUnavailable: Временный сбой хранилища.
        """

    @abstractmethod
    async def cancel(self, order_id: int) -> dtos.Order:
        """Отменяет заказ и возвращает остатки на склад.

        Args:
            order_id: Идентификатор заказа.

        Returns:
            Заказ в статусе ``cancelled``.

        Raises:
            OrderNotFound: Заказа с таким идентификатором нет.
            OrderTransitionNotAllowed: Заказ уже оплачен или отменён.
            ProductNotFound: Товар строки заказа исчез из хранилища (невозможно при
                внешнем ключе, страховка).
            StorageUnavailable: Временный сбой хранилища.
        """
