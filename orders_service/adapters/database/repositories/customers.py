"""Репозиторий клиентов на SQLAlchemy."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from orders_service.application import entities, errors, interfaces

from .. import tables
from .base import BaseRepository

# Имя ограничения уникальности по naming_convention из tables.py (uq_<таблица>_<колонка>).
_UNIQUE_EMAIL_CONSTRAINT = "uq_customers_email"


class CustomersRepo(BaseRepository, interfaces.CustomersRepo):
    """Реализация порта клиентов поверх ``AsyncSession``."""

    async def fetch_by_id(self, customer_id: int) -> entities.Customer | None:
        """Находит клиента по идентификатору через identity map сессии.

        Args:
            customer_id: Идентификатор клиента.

        Returns:
            Клиент или ``None``, если такого нет.
        """
        return await self.session.get(entities.Customer, customer_id)

    async def fetch_by_email(self, email: str) -> entities.Customer | None:
        """Находит клиента по email.

        Args:
            email: Нормализованный email клиента.

        Returns:
            Клиент или ``None``, если такого нет.
        """
        query = select(entities.Customer).where(tables.customers.c.email == email)
        return (await self.session.execute(query)).scalar_one_or_none()

    async def add(self, customer: entities.Customer) -> entities.Customer:
        """Сохраняет нового клиента, сразу отправляя INSERT в БД.

        Гонку двух одновременных регистраций закрывает ограничение уникальности БД; адаптер
        переводит её в ошибку приложения. asyncpg называет нарушенное ограничение явно;
        остальные нарушения целостности — дефект, уходят как есть.

        Args:
            customer: Клиент без ``id``.

        Returns:
            Тот же объект с проставленным ``id``.

        Raises:
            CustomerAlreadyExists: Нарушено ограничение уникальности email.
        """
        self.session.add(customer)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            cause = exc.orig.__cause__ if exc.orig is not None else None
            if getattr(cause, "constraint_name", None) == _UNIQUE_EMAIL_CONSTRAINT:
                raise errors.CustomerAlreadyExists(email=customer.email) from exc
            raise
        return customer
