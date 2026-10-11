"""Порты ядра: входящие (сценарии) и исходящие (репозитории, Unit of Work).

Входящие порты — ``Customer``, ``Product``, ``Order``: их реализуют ``services.X``, от них
зависят контроллеры и декораторы (трассировка оборачивает сценарий без правки сервиса).
Исходящие — ``CustomersRepo``, ``ProductsRepo``, ``OrdersRepo``, ``UnitOfWork``: их реализует
``adapters/database``. Реализации носят имена портов и различаются модулем импорта
(``interfaces.Order`` / ``services.Order``, ``interfaces.OrdersRepo`` /
``database.repositories.OrdersRepo``).
"""

from .customer import Customer
from .customers import CustomersRepo
from .order import Order
from .orders import OrdersRepo
from .product import Product
from .products import ProductsRepo
from .unit_of_work import UnitOfWork, UnitOfWorkFactory

__all__ = [
    "Customer",
    "CustomersRepo",
    "Order",
    "OrdersRepo",
    "Product",
    "ProductsRepo",
    "UnitOfWork",
    "UnitOfWorkFactory",
]
