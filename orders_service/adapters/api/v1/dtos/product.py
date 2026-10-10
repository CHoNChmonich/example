"""Ответы API v1 для товаров."""

from pydantic import BaseModel, ConfigDict, Field

from orders_service.application import dtos as app_dtos

from .money import Money


class ProductResponse(BaseModel):
    """Товар в ответе API.

    Attributes:
        id: Идентификатор товара.
        name: Название.
        price: Цена за единицу строкой с двумя знаками.
        stock: Доступный остаток.
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(examples=[1])
    name: str = Field(examples=["Кружка"])
    price: Money = Field(examples=["19.99"])
    stock: int = Field(examples=[98])

    @classmethod
    def from_application(cls, result: app_dtos.Product) -> "ProductResponse":
        """Строит ответ из DTO ядра.

        Args:
            result: Товар, возвращённый сервисом.

        Returns:
            Модель ответа.
        """
        return cls(id=result.id, name=result.name, price=result.price, stock=result.stock)
