"""DTO товара: вход и выход сценариев."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from .base import EntityId, Name, Price, Stock


class Product(BaseModel):
    """Товар на выходе сценария; строится из сущности через ``model_validate``.

    Attributes:
        id: Идентификатор товара.
        name: Название.
        price: Цена за единицу.
        stock: Доступный остаток.
    """

    model_config = ConfigDict(from_attributes=True)

    id: EntityId
    name: str
    price: Decimal
    stock: int


class NewProductInfo(BaseModel):
    """Данные для добавления товара.

    Attributes:
        name: Название; пробелы по краям срезаются.
        price: Цена за единицу, больше нуля, не более двух знаков после запятой.
        stock: Начальный остаток, неотрицательный.
    """

    name: Name
    price: Price
    stock: Stock
