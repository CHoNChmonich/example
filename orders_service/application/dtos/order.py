"""DTO заказа: вход и выход сценариев, параметры поиска."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from orders_service.application.entities import OrderStatus

from .base import MAX_ORDER_LINES, MAX_PAGE_LIMIT, EntityId, Offset, Quantity


class OrderLine(BaseModel):
    """Строка заказа на выходе сценария.

    Attributes:
        id: Идентификатор строки.
        product_id: Товар строки.
        quantity: Количество единиц.
        unit_price: Цена за единицу, зафиксированная при оформлении.
        total: Стоимость строки.
    """

    model_config = ConfigDict(from_attributes=True)

    id: EntityId
    product_id: int
    quantity: int
    unit_price: Decimal
    total: Decimal


class Order(BaseModel):
    """Заказ на выходе сценария; строится из сущности через ``model_validate``.

    Attributes:
        id: Идентификатор заказа.
        customer_id: Клиент, оформивший заказ.
        status: Текущий статус.
        created_at: Момент оформления.
        lines: Строки заказа.
        subtotal: Сумма до скидки.
        discount: Сумма скидки.
        total: Сумма к оплате.
    """

    model_config = ConfigDict(from_attributes=True)

    id: EntityId
    customer_id: int
    status: OrderStatus
    created_at: datetime
    lines: list[OrderLine]
    subtotal: Decimal
    discount: Decimal
    total: Decimal


def ensure_one_line_per_product(product_ids: Sequence[int]) -> None:
    """Проверяет правило заказа «каждый товар — одной строкой»; общее для ядра и HTTP-шва.

    Args:
        product_ids: Идентификаторы товаров по строкам заказа.

    Raises:
        PydanticCustomError: Среди идентификаторов есть повторы (тип ``order_duplicate_product``).
    """
    if len(product_ids) != len(set(product_ids)):
        raise PydanticCustomError(
            "order_duplicate_product", "Каждый товар указывается одной строкой заказа"
        )


class NewOrderLineInfo(BaseModel):
    """Строка нового заказа.

    Attributes:
        product_id: Товар строки.
        quantity: Количество единиц, от одной до ``MAX_LINE_QUANTITY``.
    """

    product_id: EntityId
    quantity: Quantity


class NewOrderInfo(BaseModel):
    """Данные для оформления заказа.

    Attributes:
        customer_id: Клиент, оформляющий заказ.
        lines: Строки заказа, от одной до ``MAX_ORDER_LINES``; каждый товар — одной строкой.
    """

    customer_id: EntityId
    lines: list[NewOrderLineInfo] = Field(min_length=1, max_length=MAX_ORDER_LINES)

    @field_validator("lines")
    @classmethod
    def _one_line_per_product(cls, lines: list[NewOrderLineInfo]) -> list[NewOrderLineInfo]:
        """Отклоняет заказ, где один товар встречается в нескольких строках.

        Args:
            lines: Строки заказа после валидации полей.

        Returns:
            Те же строки без изменений.

        Raises:
            PydanticCustomError: Товар повторяется.
        """
        ensure_one_line_per_product([line.product_id for line in lines])
        return lines


class FindOrders(BaseModel):
    """Параметры поиска заказов.

    Attributes:
        customer_id: Ограничить выборку заказами клиента; ``None`` — все клиенты.
        status: Ограничить выборку статусом; ``None`` — любой статус.
        limit: Размер страницы, не более ``MAX_PAGE_LIMIT``.
        offset: Смещение от начала выборки.
    """

    customer_id: EntityId | None = None
    status: OrderStatus | None = None
    limit: int = Field(default=20, ge=1, le=MAX_PAGE_LIMIT)
    offset: Offset = 0
