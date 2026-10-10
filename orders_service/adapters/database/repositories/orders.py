"""Репозиторий заказов на SQLAlchemy."""

from collections.abc import Sequence

from sqlalchemy import select

from orders_service.application import dtos, entities, interfaces

from .. import tables
from .base import BaseRepository


class OrdersRepo(BaseRepository, interfaces.OrdersRepo):
    """Реализация порта заказов поверх ``AsyncSession``."""

    async def fetch_by_id(
        self, order_id: int, *, for_update: bool = False
    ) -> entities.Order | None:
        """Находит заказ со строками по идентификатору.

        Блокируется только строка заказа; строки позиций ``selectin`` подгружает отдельным
        запросом без блокировки.

        Args:
            order_id: Идентификатор заказа.
            for_update: Заблокировать строку заказа до конца транзакции.

        Returns:
            Заказ с загруженными строками или ``None``, если такого нет.
        """
        query = select(entities.Order).where(tables.orders.c.id == order_id)
        if for_update:
            query = query.with_for_update()
        return (await self.session.execute(query)).scalar_one_or_none()

    async def fetch_all(self, filter_params: dtos.FindOrders) -> Sequence[entities.Order]:
        """Находит заказы по фильтру с динамическим ``WHERE``.

        Args:
            filter_params: Клиент, статус, лимит и смещение выборки.

        Returns:
            Заказы по возрастанию ``id`` в пределах лимита и смещения.
        """
        query = select(entities.Order)
        if filter_params.customer_id is not None:
            query = query.where(tables.orders.c.customer_id == filter_params.customer_id)
        if filter_params.status is not None:
            query = query.where(tables.orders.c.status == filter_params.status)
        query = (
            query.order_by(tables.orders.c.id)
            .limit(filter_params.limit)
            .offset(filter_params.offset)
        )
        return (await self.session.execute(query)).scalars().all()

    async def add(self, order: entities.Order) -> entities.Order:
        """Сохраняет новый заказ, сразу отправляя INSERT в БД; строки сохраняются каскадом.

        Args:
            order: Заказ без ``id`` со строками без ``id``.

        Returns:
            Тот же объект с проставленными ``id`` заказа и строк.
        """
        self.session.add(order)
        await self.session.flush()
        return order
