"""Тела запросов и параметры API v1 (``*Body``); ``to_application()`` переводит их в DTO ядра.

Модели ядра наружу не торчат: у шва свои классы и своё перечисление статуса.
"""

from .customer import CustomerCreateBody
from .order import OrderCreateBody, OrderLineCreateBody, OrderStatus
from .product import ProductCreateBody

__all__ = [
    "CustomerCreateBody",
    "OrderCreateBody",
    "OrderLineCreateBody",
    "OrderStatus",
    "ProductCreateBody",
]
