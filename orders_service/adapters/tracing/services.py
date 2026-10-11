"""Спаны сценариев: декораторы над входящими портами ``interfaces.Customer/Product/Order``.

Имя спана — ``Класс.метод`` реализации (``Order.place``): низкая кардинальность, совпадает с
кодом и с маршрутом API. Контракт методов — у портов; здесь каждый метод делегирует вызов под
спаном, исход которого ставит политика ``span`` (ошибка ядра — атрибут кода без ERROR,
``StorageUnavailable`` — ERROR с исходной ошибкой хранилища).
"""

from orders_service.application import dtos, interfaces

from .spans import span


class TracedCustomer(interfaces.Customer):
    """Сценарии клиента под спанами.

    Паттерн: Decorator (GoF) — тот же порт, делегирование оборачиваемому сервису.
    """

    def __init__(self, inner: interfaces.Customer) -> None:
        """Запоминает оборачиваемые сценарии.

        Args:
            inner: Реализация порта, которой делегируются вызовы.
        """
        self._inner = inner

    async def add(self, new_customer_info: dtos.NewCustomerInfo) -> dtos.Customer:
        """Делегирует регистрацию клиента под спаном ``Customer.add``."""
        with span("Customer.add"):
            return await self._inner.add(new_customer_info)

    async def get(self, customer_id: int) -> dtos.Customer:
        """Делегирует чтение клиента под спаном ``Customer.get``."""
        with span("Customer.get"):
            return await self._inner.get(customer_id)


class TracedProduct(interfaces.Product):
    """Сценарии товара под спанами.

    Паттерн: Decorator (GoF) — тот же порт, делегирование оборачиваемому сервису.
    """

    def __init__(self, inner: interfaces.Product) -> None:
        """Запоминает оборачиваемые сценарии.

        Args:
            inner: Реализация порта, которой делегируются вызовы.
        """
        self._inner = inner

    async def add(self, new_product_info: dtos.NewProductInfo) -> dtos.Product:
        """Делегирует добавление товара под спаном ``Product.add``."""
        with span("Product.add"):
            return await self._inner.add(new_product_info)

    async def get(self, product_id: int) -> dtos.Product:
        """Делегирует чтение товара под спаном ``Product.get``."""
        with span("Product.get"):
            return await self._inner.get(product_id)


class TracedOrder(interfaces.Order):
    """Сценарии заказа под спанами.

    Паттерн: Decorator (GoF) — тот же порт, делегирование оборачиваемому сервису.
    """

    def __init__(self, inner: interfaces.Order) -> None:
        """Запоминает оборачиваемые сценарии.

        Args:
            inner: Реализация порта, которой делегируются вызовы.
        """
        self._inner = inner

    async def place(self, new_order_info: dtos.NewOrderInfo) -> dtos.Order:
        """Делегирует оформление заказа под спаном ``Order.place``."""
        with span("Order.place"):
            return await self._inner.place(new_order_info)

    async def get(self, order_id: int) -> dtos.Order:
        """Делегирует чтение заказа под спаном ``Order.get``."""
        with span("Order.get"):
            return await self._inner.get(order_id)

    async def find(self, filter_params: dtos.FindOrders) -> list[dtos.Order]:
        """Делегирует поиск заказов под спаном ``Order.find``."""
        with span("Order.find"):
            return await self._inner.find(filter_params)

    async def pay(self, order_id: int) -> dtos.Order:
        """Делегирует оплату заказа под спаном ``Order.pay``."""
        with span("Order.pay"):
            return await self._inner.pay(order_id)

    async def cancel(self, order_id: int) -> dtos.Order:
        """Делегирует отмену заказа под спаном ``Order.cancel``."""
        with span("Order.cancel"):
            return await self._inner.cancel(order_id)
