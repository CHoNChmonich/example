"""Настройки подключения к PostgreSQL."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from orders_service import ENV_FILE


class Settings(BaseSettings):
    """Подключение к PostgreSQL: переменные окружения и ``.env`` в корне проекта.

    Attributes:
        POSTGRES_USER: Пользователь БД.
        POSTGRES_PASSWORD: Пароль пользователя; в логи не попадает.
        POSTGRES_DB: Имя базы данных.
        POSTGRES_HOST: Хост БД; в compose переопределяется именем сервиса.
        POSTGRES_PORT: Порт БД.
        POSTGRES_ECHO_SQL: Писать ли SQL-запросы в лог.
    """

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    POSTGRES_USER: str
    POSTGRES_PASSWORD: SecretStr
    POSTGRES_DB: str
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = Field(default=5432, gt=0, lt=65536)
    POSTGRES_ECHO_SQL: bool = False

    @property
    def database_url(self) -> str:
        """URL подключения для асинхронного движка SQLAlchemy (драйвер asyncpg)."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD.get_secret_value()}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )
