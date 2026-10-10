"""Тела запросов API v1 для товаров."""

from pydantic import BaseModel, ConfigDict, Field

from orders_service.application import dtos as app_dtos


class ProductCreateBody(BaseModel):
    """Тело запроса на добавление товара.

    Attributes:
        name: Название; пробелы по краям срезаются.
        price: Цена за единицу, больше нуля, не более двух знаков после запятой.
        stock: Начальный остаток на складе, неотрицательный.
    """

    model_config = ConfigDict(extra="forbid")

    name: app_dtos.Name = Field(examples=["Кружка"])
    price: app_dtos.Price = Field(examples=["19.99"])
    stock: app_dtos.Stock = Field(description="Начальный остаток на складе", examples=[100])

    def to_application(self) -> app_dtos.NewProductInfo:
        """Переводит тело запроса в DTO ядра.

        Returns:
            Данные для добавления товара.
        """
        return app_dtos.NewProductInfo(name=self.name, price=self.price, stock=self.stock)
