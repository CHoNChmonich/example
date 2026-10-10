"""Настройки уровня приложения, которые не принадлежат ни одному адаптеру."""

from decimal import Decimal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from orders_service import ENV_FILE


class Settings(BaseSettings):
    """Настройки уровня приложения: переменные окружения и ``.env`` в корне проекта.

    Attributes:
        LOG_LEVEL: Уровень корневого логгера (``DEBUG``, ``INFO``, …); регистр не важен.
        DISCOUNT_MIN_QUANTITY: Порог объёмной скидки — общее количество единиц в заказе,
            с которого (включительно) она действует.
        DISCOUNT_PERCENT: Размер объёмной скидки в процентах от суммы заказа.
    """

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    LOG_LEVEL: str = "INFO"
    DISCOUNT_MIN_QUANTITY: int = Field(default=10, ge=1)
    DISCOUNT_PERCENT: Decimal = Field(default=Decimal("5"), ge=0, le=100)
