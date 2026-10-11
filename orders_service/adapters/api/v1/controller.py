"""Обработчики HTTP v1: разбор запроса → DTO ядра → сценарий → DTO ответа.

Класс получает входящие порты сценариев (``interfaces.Customer/Product/Order``) через
конструктор из composition root — тот же «чистый» DI, что и у остальных адаптеров;
FastAPI-``Depends`` не используется. Зависимость от порта, а не от ``services.X``, позволяет
composition root подставить декоратор (трассировка) без правки контроллера.
``Path``/``Query``/``Body`` ниже — разбор запроса, а не внедрение зависимостей. Границы
параметров пути и запроса — те же, что у DTO ядра (``dtos.base``).
"""

from typing import Annotated

from fastapi import Body, Path, Query

from orders_service.adapters.api.v1 import dtos as api_dtos
from orders_service.adapters.api.v1 import schemas as api_schemas
from orders_service.application import dtos as app_dtos
from orders_service.application import interfaces

EntityIdPath = Annotated[int, Path(ge=1, le=app_dtos.MAX_INT32)]


class Controller:
    """Обработчики API v1.

    Attributes:
        customer: Сценарии клиента.
        product: Сценарии товара.
        order: Сценарии заказа.
    """

    def __init__(
        self,
        *,
        customer: interfaces.Customer,
        product: interfaces.Product,
        order: interfaces.Order,
    ) -> None:
        """Принимает порты сценариев из composition root.

        Args:
            customer: Сценарии клиента.
            product: Сценарии товара.
            order: Сценарии заказа.
        """
        self.customer = customer
        self.product = product
        self.order = order

    async def create_customer(
        self, body: Annotated[api_schemas.CustomerCreateBody, Body()]
    ) -> api_dtos.CustomerResponse:
        """Регистрирует клиента.

        Args:
            body: Имя и email нового клиента.

        Returns:
            Зарегистрированный клиент (201).

        Raises:
            CustomerAlreadyExists: Email занят (409).
            StorageUnavailable: Временный сбой хранилища (503).
        """
        result = await self.customer.add(body.to_application())
        return api_dtos.CustomerResponse.from_application(result)

    async def get_customer(self, customer_id: EntityIdPath) -> api_dtos.CustomerResponse:
        """Возвращает клиента по идентификатору.

        Args:
            customer_id: Идентификатор клиента из пути.

        Returns:
            Найденный клиент.

        Raises:
            CustomerNotFound: Клиента нет (404).
            StorageUnavailable: Временный сбой хранилища (503).
        """
        result = await self.customer.get(customer_id)
        return api_dtos.CustomerResponse.from_application(result)

    async def create_product(
        self, body: Annotated[api_schemas.ProductCreateBody, Body()]
    ) -> api_dtos.ProductResponse:
        """Добавляет товар с начальным остатком.

        Args:
            body: Название, цена и начальный остаток.

        Returns:
            Добавленный товар (201).

        Raises:
            StorageUnavailable: Временный сбой хранилища (503).
        """
        result = await self.product.add(body.to_application())
        return api_dtos.ProductResponse.from_application(result)

    async def get_product(self, product_id: EntityIdPath) -> api_dtos.ProductResponse:
        """Возвращает товар по идентификатору.

        Args:
            product_id: Идентификатор товара из пути.

        Returns:
            Найденный товар.

        Raises:
            ProductNotFound: Товара нет (404).
            StorageUnavailable: Временный сбой хранилища (503).
        """
        result = await self.product.get(product_id)
        return api_dtos.ProductResponse.from_application(result)

    async def place_order(
        self, body: Annotated[api_schemas.OrderCreateBody, Body()]
    ) -> api_dtos.OrderResponse:
        """Оформляет заказ: резерв остатков, скидка и сохранение одной транзакцией.

        Args:
            body: Клиент и строки заказа.

        Returns:
            Оформленный заказ (201).

        Raises:
            CustomerNotFound: Клиента нет (404).
            ProductNotFound: Какого-то из товаров нет (404).
            InsufficientStock: Остатка не хватает (400).
            StorageUnavailable: Временный сбой хранилища (503).
        """
        result = await self.order.place(body.to_application())
        return api_dtos.OrderResponse.from_application(result)

    async def get_order(self, order_id: EntityIdPath) -> api_dtos.OrderResponse:
        """Возвращает заказ по идентификатору.

        Args:
            order_id: Идентификатор заказа из пути.

        Returns:
            Найденный заказ со строками.

        Raises:
            OrderNotFound: Заказа нет (404).
            StorageUnavailable: Временный сбой хранилища (503).
        """
        result = await self.order.get(order_id)
        return api_dtos.OrderResponse.from_application(result)

    async def list_orders(
        self,
        customer_id: Annotated[int | None, Query(ge=1, le=app_dtos.MAX_INT32)] = None,
        status: Annotated[api_schemas.OrderStatus | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=app_dtos.MAX_PAGE_LIMIT)] = 20,
        offset: Annotated[int, Query(ge=0, le=app_dtos.MAX_INT32)] = 0,
    ) -> api_dtos.OrderListResponse:
        """Находит заказы по клиенту и статусу.

        Args:
            customer_id: Ограничить выборку заказами клиента.
            status: Ограничить выборку статусом.
            limit: Размер страницы.
            offset: Смещение от начала выборки.

        Returns:
            Страница заказов по возрастанию идентификатора; пустая, если ничего не найдено.

        Raises:
            StorageUnavailable: Временный сбой хранилища (503).
        """
        results = await self.order.find(
            app_dtos.FindOrders(
                customer_id=customer_id,
                status=status.to_application() if status is not None else None,
                limit=limit,
                offset=offset,
            )
        )
        return api_dtos.OrderListResponse.from_application(results)

    async def pay_order(self, order_id: EntityIdPath) -> api_dtos.OrderResponse:
        """Оплачивает заказ (``new → paid``).

        Args:
            order_id: Идентификатор заказа из пути.

        Returns:
            Заказ в статусе ``paid``.

        Raises:
            OrderNotFound: Заказа нет (404).
            OrderTransitionNotAllowed: Заказ уже оплачен или отменён (400).
            StorageUnavailable: Временный сбой хранилища (503).
        """
        result = await self.order.pay(order_id)
        return api_dtos.OrderResponse.from_application(result)

    async def cancel_order(self, order_id: EntityIdPath) -> api_dtos.OrderResponse:
        """Отменяет заказ и возвращает остатки (``new → cancelled``).

        Args:
            order_id: Идентификатор заказа из пути.

        Returns:
            Заказ в статусе ``cancelled``.

        Raises:
            OrderNotFound: Заказа нет (404).
            OrderTransitionNotAllowed: Заказ уже оплачен или отменён (400).
            StorageUnavailable: Временный сбой хранилища (503).
        """
        result = await self.order.cancel(order_id)
        return api_dtos.OrderResponse.from_application(result)

    async def healthcheck(self) -> dict[str, str]:
        """Служебная проверка живости процесса; к хранилищу не обращается.

        Returns:
            ``{"status": "ok"}``.
        """
        return {"status": "ok"}
