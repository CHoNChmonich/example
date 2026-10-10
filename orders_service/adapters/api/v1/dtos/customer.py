"""Ответы API v1 для клиентов."""

from pydantic import BaseModel, ConfigDict, Field

from orders_service.application import dtos as app_dtos


class CustomerResponse(BaseModel):
    """Клиент в ответе API.

    Attributes:
        id: Идентификатор клиента.
        name: Имя клиента.
        email: Нормализованный email.
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(examples=[1])
    name: str = Field(examples=["Иван Петров"])
    email: str = Field(examples=["ivan@example.com"])

    @classmethod
    def from_application(cls, result: app_dtos.Customer) -> "CustomerResponse":
        """Строит ответ из DTO ядра.

        Args:
            result: Клиент, возвращённый сервисом.

        Returns:
            Модель ответа.
        """
        return cls(id=result.id, name=result.name, email=result.email)
