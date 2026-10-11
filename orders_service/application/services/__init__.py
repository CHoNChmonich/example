"""Сценарии использования: сервис на сущность с набором методов.

Каждый публичный метод — граница транзакции: он открывает ``async with self.uow_factory()``
и при записи вызывает ``uow.commit()``. Сервисы реализуют входящие порты
(``interfaces.Customer/Product/Order``) и зависят только от исходящих портов ``interfaces``
и доменных абстракций (``entities.DiscountPolicy``).
"""

from .customer import Customer
from .order import Order
from .product import Product

__all__ = ["Customer", "Order", "Product"]
