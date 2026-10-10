"""Модели обмена ядра с внешними слоями (Pydantic).

``New*Info`` — вход сценариев, ``Customer``/``Product``/``Order`` — выход (строятся из сущностей
через ``model_validate``), ``FindOrders`` — параметры поиска. Между слоями передаются только они
и сущности, не dict/list. Ограничения полей (``base``) общие с HTTP-швом.
"""

from .base import (
    MAX_INT32,
    MAX_LINE_QUANTITY,
    MAX_ORDER_LINES,
    MAX_PAGE_LIMIT,
    Email,
    EntityId,
    Name,
    Offset,
    Price,
    Quantity,
    Stock,
)
from .customer import Customer, NewCustomerInfo
from .order import (
    FindOrders,
    NewOrderInfo,
    NewOrderLineInfo,
    Order,
    OrderLine,
    ensure_one_line_per_product,
)
from .product import NewProductInfo, Product

__all__ = [
    "MAX_INT32",
    "MAX_LINE_QUANTITY",
    "MAX_ORDER_LINES",
    "MAX_PAGE_LIMIT",
    "Customer",
    "Email",
    "EntityId",
    "FindOrders",
    "Name",
    "NewCustomerInfo",
    "NewOrderInfo",
    "NewOrderLineInfo",
    "NewProductInfo",
    "Offset",
    "Order",
    "OrderLine",
    "Price",
    "Product",
    "Quantity",
    "Stock",
    "ensure_one_line_per_product",
]
