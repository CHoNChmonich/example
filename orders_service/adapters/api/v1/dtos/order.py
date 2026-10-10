"""Ответы API v1 для заказов."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from orders_service.adapters.api.v1.schemas.order import OrderStatus
from orders_service.application import dtos as app_dtos

from .money import Money


class OrderLineResponse(BaseModel):
    """Строка заказа в ответе API.

    Attributes:
        id: Идентификатор строки.
        product_id: Товар строки.
        quantity: Количество единиц.
        unit_price: Цена за единицу строкой с двумя знаками.
        total: Стоимость строки строкой с двумя знаками.
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(examples=[1])
    product_id: int = Field(examples=[1])
    quantity: int = Field(examples=[2])
    unit_price: Money = Field(examples=["19.99"])
    total: Money = Field(examples=["39.98"])

    @classmethod
    def from_application(cls, result: app_dtos.OrderLine) -> "OrderLineResponse":
        """Строит ответ из DTO ядра.

        Args:
            result: Строка заказа, возвращённая сервисом.

        Returns:
            Модель ответа.
        """
        return cls(
            id=result.id,
            product_id=result.product_id,
            quantity=result.quantity,
            unit_price=result.unit_price,
            total=result.total,
        )


class OrderResponse(BaseModel):
    """Заказ в ответе API.

    Attributes:
        id: Идентификатор заказа.
        customer_id: Клиент, оформивший заказ.
        status: Статус заказа.
        created_at: Момент оформления в UTC.
        lines: Строки заказа.
        subtotal: Сумма до скидки строкой с двумя знаками.
        discount: Сумма скидки строкой с двумя знаками.
        total: Сумма к оплате строкой с двумя знаками.
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(examples=[1])
    customer_id: int = Field(examples=[1])
    status: OrderStatus = Field(examples=["new"])
    created_at: datetime = Field(examples=["2026-10-10T12:00:00Z"])
    lines: list[OrderLineResponse]
    subtotal: Money = Field(examples=["39.98"])
    discount: Money = Field(examples=["0.00"])
    total: Money = Field(examples=["39.98"])

    @classmethod
    def from_application(cls, result: app_dtos.Order) -> "OrderResponse":
        """Строит ответ из DTO ядра.

        Args:
            result: Заказ, возвращённый сервисом.

        Returns:
            Модель ответа.
        """
        return cls(
            id=result.id,
            customer_id=result.customer_id,
            status=OrderStatus.from_application(result.status),
            created_at=result.created_at,
            lines=[OrderLineResponse.from_application(line) for line in result.lines],
            subtotal=result.subtotal,
            discount=result.discount,
            total=result.total,
        )


class OrderListResponse(BaseModel):
    """Страница заказов в ответе API.

    Attributes:
        items: Заказы по возрастанию идентификатора.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[OrderResponse]

    @classmethod
    def from_application(cls, results: list[app_dtos.Order]) -> "OrderListResponse":
        """Строит ответ из списка DTO ядра.

        Args:
            results: Заказы, возвращённые сервисом.

        Returns:
            Модель ответа.
        """
        return cls(items=[OrderResponse.from_application(result) for result in results])
