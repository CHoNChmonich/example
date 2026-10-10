"""Сценарии заказа."""

from collections.abc import Mapping

from orders_service.application import dtos, entities, errors, interfaces
from orders_service.application.transactional import transactional


class Order:
    """Сценарии заказа; каждый публичный метод — отдельная транзакция.

    Оформление и отмена — многорепозиторные транзакции (клиенты, товары, заказы в одном
    Unit of Work): остатки и заказ меняются атомарно либо не меняются вовсе.

    Attributes:
        uow_factory: Фабрика Unit of Work, из которой обёртка берёт транзакцию на вызов.
        discount_policy: Политика скидки (Strategy), применяемая при оформлении.
    """

    def __init__(
        self,
        uow_factory: interfaces.UnitOfWorkFactory,
        discount_policy: entities.DiscountPolicy,
    ) -> None:
        """Принимает зависимости из composition root.

        Args:
            uow_factory: Фабрика Unit of Work.
            discount_policy: Политика скидки, выбранная при сборке приложения.
        """
        self.uow_factory = uow_factory
        self.discount_policy = discount_policy

    @transactional
    async def place(
        self, uow: interfaces.UnitOfWork, new_order_info: dtos.NewOrderInfo
    ) -> dtos.Order:
        """Оформляет заказ: проверяет клиента и товары, резервирует остатки, применяет скидку.

        Args:
            uow: Транзакция, выданная обёрткой ``@transactional``.
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
        if await uow.customers.fetch_by_id(new_order_info.customer_id) is None:
            raise errors.CustomerNotFound(id=new_order_info.customer_id)

        requested = {line.product_id: line.quantity for line in new_order_info.lines}
        products = await _lock_products(uow, requested)

        lines: list[entities.OrderLine] = []
        for product_id, quantity in requested.items():
            product = products[product_id]
            product.reserve(quantity)
            lines.append(
                entities.OrderLine(
                    product_id=product_id, quantity=quantity, unit_price=product.price
                )
            )

        order = entities.Order(customer_id=new_order_info.customer_id, lines=lines)
        order.apply_discount(self.discount_policy)
        added = await uow.orders.add(order)
        return dtos.Order.model_validate(added)

    @transactional
    async def get(self, uow: interfaces.UnitOfWork, order_id: int) -> dtos.Order:
        """Возвращает заказ по идентификатору.

        Args:
            uow: Транзакция, выданная обёрткой ``@transactional``.
            order_id: Идентификатор заказа.

        Returns:
            Найденный заказ со строками.

        Raises:
            OrderNotFound: Заказа с таким идентификатором нет.
            StorageUnavailable: Временный сбой хранилища.
        """
        order = await uow.orders.fetch_by_id(order_id)
        if order is None:
            raise errors.OrderNotFound(id=order_id)
        return dtos.Order.model_validate(order)

    @transactional
    async def find(
        self, uow: interfaces.UnitOfWork, filter_params: dtos.FindOrders
    ) -> list[dtos.Order]:
        """Находит заказы по фильтру.

        Args:
            uow: Транзакция, выданная обёрткой ``@transactional``.
            filter_params: Клиент, статус, лимит и смещение выборки.

        Returns:
            Заказы по возрастанию идентификатора; пустой список, если ничего не найдено.

        Raises:
            StorageUnavailable: Временный сбой хранилища.
        """
        orders = await uow.orders.fetch_all(filter_params)
        return [dtos.Order.model_validate(order) for order in orders]

    @transactional
    async def pay(self, uow: interfaces.UnitOfWork, order_id: int) -> dtos.Order:
        """Оплачивает заказ.

        Args:
            uow: Транзакция, выданная обёрткой ``@transactional``.
            order_id: Идентификатор заказа.

        Returns:
            Заказ в статусе ``paid``.

        Raises:
            OrderNotFound: Заказа с таким идентификатором нет.
            OrderTransitionNotAllowed: Заказ уже оплачен или отменён.
            StorageUnavailable: Временный сбой хранилища.
        """
        order = await uow.orders.fetch_by_id(order_id, for_update=True)
        if order is None:
            raise errors.OrderNotFound(id=order_id)
        order.pay()
        return dtos.Order.model_validate(order)

    @transactional
    async def cancel(self, uow: interfaces.UnitOfWork, order_id: int) -> dtos.Order:
        """Отменяет заказ и возвращает остатки на склад.

        Args:
            uow: Транзакция, выданная обёрткой ``@transactional``.
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
        order = await uow.orders.fetch_by_id(order_id, for_update=True)
        if order is None:
            raise errors.OrderNotFound(id=order_id)
        order.cancel()

        to_release = {line.product_id: line.quantity for line in order.lines}
        products = await _lock_products(uow, to_release)
        for product_id, quantity in to_release.items():
            products[product_id].release(quantity)
        return dtos.Order.model_validate(order)


async def _lock_products(
    uow: interfaces.UnitOfWork, quantities: Mapping[int, int]
) -> dict[int, entities.Product]:
    """Блокирует товары из словаря «id → количество» и возвращает их по идентификатору.

    Общий шаг оформления и отмены (правило «общая логика — хелпер, принимающий uow»).

    Args:
        uow: Транзакция, в которой берутся блокировки.
        quantities: Идентификаторы товаров и запрошенные количества; порядок ключей —
            порядок строк заказа.

    Returns:
        Заблокированные товары по идентификатору, в порядке ``quantities``.

    Raises:
        ProductNotFound: Первый отсутствующий товар в порядке ``quantities``.
    """
    products = await uow.products.fetch_by_ids(list(quantities), for_update=True)
    products_by_id = {product.id: product for product in products}
    locked: dict[int, entities.Product] = {}
    for product_id in quantities:
        product = products_by_id.get(product_id)
        if product is None:
            raise errors.ProductNotFound(id=product_id)
        locked[product_id] = product
    return locked
