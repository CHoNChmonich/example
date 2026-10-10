"""Исходящие порты ядра: репозитории и Unit of Work.

Входящих портов нет — контроллеры зависят от конкретных ``services.X`` (правило hex_arch).
Реализации портов живут в ``adapters/database`` и носят те же имена: различаются модулем
импорта (``interfaces.OrdersRepo`` / ``database.repositories.OrdersRepo``).
"""

from .customers import CustomersRepo
from .orders import OrdersRepo
from .products import ProductsRepo
from .unit_of_work import UnitOfWork, UnitOfWorkFactory

__all__ = [
    "CustomersRepo",
    "OrdersRepo",
    "ProductsRepo",
    "UnitOfWork",
    "UnitOfWorkFactory",
]
