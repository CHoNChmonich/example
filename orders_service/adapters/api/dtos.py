"""Общие модели ответов API, не привязанные к версии."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    """Единая форма любой ошибки API.

    Attributes:
        error: Текст ошибки для человека.
        code: Машинный код ошибки в snake_case.
        context: Детали ошибки: идентификаторы, количества, перечень нарушений валидации.
    """

    model_config = ConfigDict(extra="forbid")

    error: str = Field(examples=["Клиент с id 42 не найден"])
    code: str = Field(examples=["customer_not_found"])
    context: dict[str, Any] = Field(default_factory=dict, examples=[{"id": 42}])
