"""Тела запросов и параметры API v1 для заказов."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from orders_service.application import dtos as app_dtos
from orders_service.application import entities


class OrderStatus(StrEnum):
    """Статус заказа на HTTP-краю; ``entities.OrderStatus`` наружу не выдаётся."""

    new = "new"
    paid = "paid"
    cancelled = "cancelled"

    def to_application(self) -> entities.OrderStatus:
        """Переводит статус шва в статус ядра.

        Returns:
            Член ``entities.OrderStatus`` с тем же значением.
        """
        return entities.OrderStatus(self.value)

    @classmethod
    def from_application(cls, status: entities.OrderStatus) -> "OrderStatus":
        """Переводит статус ядра в статус шва.

        Args:
            status: Статус заказа из ядра.

        Returns:
            Член перечисления шва с тем же значением.
        """
        return cls(status.value)


class OrderLineCreateBody(BaseModel):
    """Строка заказа в теле запроса.

    Attributes:
        product_id: Идентификатор товара.
        quantity: Количество единиц, от одной до ``MAX_LINE_QUANTITY``.
    """

    model_config = ConfigDict(extra="forbid")

    product_id: app_dtos.EntityId = Field(examples=[1])
    quantity: app_dtos.Quantity = Field(examples=[2])


class OrderCreateBody(BaseModel):
    """Тело запроса на оформление заказа.

    Attributes:
        customer_id: Идентификатор клиента.
        lines: Позиции заказа, от одной до ``MAX_ORDER_LINES``; каждый товар — одной строкой.
    """

    model_config = ConfigDict(extra="forbid")

    customer_id: app_dtos.EntityId = Field(examples=[1])
    lines: list[OrderLineCreateBody] = Field(
        min_length=1,
        max_length=app_dtos.MAX_ORDER_LINES,
        description="Позиции заказа; каждый товар — одной строкой.",
        examples=[[{"product_id": 1, "quantity": 2}, {"product_id": 2, "quantity": 8}]],
    )

    @field_validator("lines")
    @classmethod
    def _one_line_per_product(cls, lines: list[OrderLineCreateBody]) -> list[OrderLineCreateBody]:
        """Применяет правило ядра «один товар — одной строкой» уже на границе HTTP.

        Так клиент получает 400 с понятным типом ошибки, а не 500 из ``to_application()``.

        Args:
            lines: Позиции заказа после валидации полей.

        Returns:
            Те же позиции без изменений.

        Raises:
            PydanticCustomError: Товар повторяется (тип ``order_duplicate_product``).
        """
        app_dtos.ensure_one_line_per_product([line.product_id for line in lines])
        return lines

    def to_application(self) -> app_dtos.NewOrderInfo:
        """Переводит тело запроса в DTO ядра.

        Returns:
            Данные для оформления заказа.
        """
        return app_dtos.NewOrderInfo(
            customer_id=self.customer_id,
            lines=[
                app_dtos.NewOrderLineInfo(product_id=line.product_id, quantity=line.quantity)
                for line in self.lines
            ],
        )
