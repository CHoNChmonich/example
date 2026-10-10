"""DTO клиента: вход и выход сценариев."""

from pydantic import BaseModel, ConfigDict

from .base import Email, EntityId, Name


class Customer(BaseModel):
    """Клиент на выходе сценария; строится из сущности через ``model_validate``.

    Attributes:
        id: Идентификатор клиента.
        name: Имя клиента.
        email: Нормализованный email.
    """

    model_config = ConfigDict(from_attributes=True)

    id: EntityId
    name: str
    email: str


class NewCustomerInfo(BaseModel):
    """Данные для регистрации клиента.

    Attributes:
        name: Имя; пробелы по краям срезаются.
        email: Email только из ASCII; приводится к нижнему регистру.
    """

    name: Name
    email: Email
