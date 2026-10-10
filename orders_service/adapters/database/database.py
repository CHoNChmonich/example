"""Движок и фабрика сессий SQLAlchemy."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .settings import Settings


class Database:
    """Движок и фабрика сессий SQLAlchemy; открывается и закрывается в lifespan приложения.

    Attributes:
        session_factory: Фабрика сессий с ``expire_on_commit=False``: после commit
            к сущностям можно обращаться без новых запросов.
    """

    def __init__(self, settings: Settings) -> None:
        """Создаёт движок и фабрику сессий; соединения открываются лениво.

        Пул создаётся с ``pool_pre_ping``: мёртвое простаивающее соединение проверяется
        до выдачи из пула, а не на первом запросе транзакции.

        Args:
            settings: Параметры подключения к PostgreSQL.
        """
        self._settings = settings
        self._engine: AsyncEngine = create_async_engine(
            settings.database_url,
            echo=settings.POSTGRES_ECHO_SQL,
            pool_pre_ping=True,
        )
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

    async def aopen(self) -> None:
        """Проверяет доступность БД на старте: ошибка конфигурации — ошибка запуска.

        Raises:
            RuntimeError: К БД не удалось подключиться; причина — в тексте и в ``__cause__``.
        """
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception as exc:
            raise RuntimeError(
                f"PostgreSQL недоступен по адресу "
                f"{self._settings.POSTGRES_HOST}:{self._settings.POSTGRES_PORT}: {exc}"
            ) from exc

    async def aclose(self) -> None:
        """Закрывает пул соединений при остановке приложения."""
        await self._engine.dispose()
