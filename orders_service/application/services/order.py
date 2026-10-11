"""Сценарии заказа."""

from collections.abc import Mapping

from orders_service.application import dtos, entities, errors, interfaces


class Order(interfaces.Order):
    """Сценарии заказа; каждый публичный метод — отдельная транзакция.

    Оформление и отмена — многорепозиторные транзакции (клиенты, товары, заказы в одном
    Unit of Work): остатки и заказ меняются атомарно либо не меняются вовсе. Контракт
    методов — у порта ``interfaces.Order``; здесь — как он исполняется.

    Attributes:
        uow_factory: Вызываемый объект, создающий новый Unit of Work на каждый вызов метода.
        discount_policy: Политика скидки (Strategy), применяемая при оформлении.
    """

    def __init__(
        self,
        uow_factory: interfaces.UnitOfWorkFactory,
        discount_policy: entities.DiscountPolicy,
    ) -> None:
        """Принимает зависимости из composition root.

        Args:
            uow_factory: Фабрика Unit of Work — вызываемый объект без аргументов.
            discount_policy: Политика скидки, выбранная при сборке приложения.
        """
        self.uow_factory = uow_factory
        self.discount_policy = discount_policy

    async def place(self, new_order_info: dtos.NewOrderInfo) -> dtos.Order:
        """Оформляет заказ: товары блокируются ``FOR UPDATE`` в порядке идентификаторов.

        Резервирование остатков, скидка и запись заказа — в одной транзакции; ошибка на любой
        строке откатывает всё.

        Args:
            new_order_info: Клиент и строки заказа.

        Returns:
            Сохранённый заказ со строками, скидкой и суммой к оплате.
        """
        async with self.uow_factory() as uow:
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
            await uow.commit()
            return dtos.Order.model_validate(added)

    async def get(self, order_id: int) -> dtos.Order:
        """Возвращает заказ по идентификатору; чтение без commit.

        Args:
            order_id: Идентификатор заказа.

        Returns:
            Найденный заказ со строками.
        """
        async with self.uow_factory() as uow:
            order = await uow.orders.fetch_by_id(order_id)
            if order is None:
                raise errors.OrderNotFound(id=order_id)
            return dtos.Order.model_validate(order)

    async def find(self, filter_params: dtos.FindOrders) -> list[dtos.Order]:
        """Находит заказы по фильтру; чтение без commit.

        Args:
            filter_params: Клиент, статус, лимит и смещение выборки.

        Returns:
            Заказы по возрастанию идентификатора; пустой список, если ничего не найдено.
        """
        async with self.uow_factory() as uow:
            orders = await uow.orders.fetch_all(filter_params)
            return [dtos.Order.model_validate(order) for order in orders]

    async def pay(self, order_id: int) -> dtos.Order:
        """Оплачивает заказ: строка заказа блокируется ``FOR UPDATE`` на время перехода.

        Args:
            order_id: Идентификатор заказа.

        Returns:
            Заказ в статусе ``paid``.
        """
        async with self.uow_factory() as uow:
            order = await uow.orders.fetch_by_id(order_id, for_update=True)
            if order is None:
                raise errors.OrderNotFound(id=order_id)
            order.pay()
            await uow.commit()
            return dtos.Order.model_validate(order)

    async def cancel(self, order_id: int) -> dtos.Order:
        """Отменяет заказ: блокирует строку заказа, затем товары, и возвращает остатки.

        Args:
            order_id: Идентификатор заказа.

        Returns:
            Заказ в статусе ``cancelled``.
        """
        async with self.uow_factory() as uow:
            order = await uow.orders.fetch_by_id(order_id, for_update=True)
            if order is None:
                raise errors.OrderNotFound(id=order_id)
            order.cancel()

            to_release = {line.product_id: line.quantity for line in order.lines}
            products = await _lock_products(uow, to_release)
            for product_id, quantity in to_release.items():
                products[product_id].release(quantity)
            await uow.commit()
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
