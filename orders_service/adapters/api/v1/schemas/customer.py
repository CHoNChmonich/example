"""Тела запросов API v1 для клиентов."""

from pydantic import BaseModel, ConfigDict, Field

from orders_service.application import dtos as app_dtos


class CustomerCreateBody(BaseModel):
    """Тело запроса на регистрацию клиента.

    Ограничения полей — те же типы, что у DTO ядра: тело, прошедшее валидацию на границе,
    гарантированно принимается ``to_application()``.

    Attributes:
        name: Имя клиента; пробелы по краям срезаются.
        email: Email только из ASCII; приводится к нижнему регистру.
    """

    model_config = ConfigDict(extra="forbid")

    name: app_dtos.Name = Field(examples=["Иван Петров"])
    email: app_dtos.Email = Field(examples=["ivan@example.com"])

    def to_application(self) -> app_dtos.NewCustomerInfo:
        """Переводит тело запроса в DTO ядра.

        Returns:
            Данные для регистрации клиента.
        """
        return app_dtos.NewCustomerInfo(name=self.name, email=self.email)
