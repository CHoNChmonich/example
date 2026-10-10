"""Репозиторий товаров на SQLAlchemy."""

from collections.abc import Sequence

from sqlalchemy import select

from orders_service.application import entities, interfaces

from .. import tables
from .base import BaseRepository


class ProductsRepo(BaseRepository, interfaces.ProductsRepo):
    """Реализация порта товаров поверх ``AsyncSession``."""

    async def fetch_by_id(self, product_id: int) -> entities.Product | None:
        """Находит товар по идентификатору через identity map сессии, без блокировки.

        Args:
            product_id: Идентификатор товара.

        Returns:
            Товар или ``None``, если такого нет.
        """
        return await self.session.get(entities.Product, product_id)

    async def fetch_by_ids(
        self, product_ids: Sequence[int], *, for_update: bool = False
    ) -> Sequence[entities.Product]:
        """Находит товары по списку идентификаторов одним запросом.

        ``ORDER BY id`` в самом запросе задаёт порядок захвата блокировок (``LockRows`` над
        ``Sort``): одинаковый порядок у всех транзакций исключает взаимную блокировку. При
        ``for_update`` запрос идёт с ``populate_existing``: товар, прочитанный ранее в этой
        сессии без блокировки, перечитывается из БД — под блокировкой состояние должно быть
        актуальным. Несохранённые изменения этой же транзакции не теряются благодаря
        autoflush сессии (он сбрасывает их в БД перед SELECT); фабрика сессий его не отключает.

        Args:
            product_ids: Идентификаторы товаров; отсутствующие молча пропускаются.
            for_update: Заблокировать строки до конца транзакции (``SELECT … FOR UPDATE``).

        Returns:
            Найденные товары по возрастанию ``id``; пустая последовательность для пустого
            списка идентификаторов, без запроса к БД.
        """
        if not product_ids:
            return []
        query = (
            select(entities.Product)
            .where(tables.products.c.id.in_(product_ids))
            .order_by(tables.products.c.id)
        )
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(query)).scalars().all()

    async def add(self, product: entities.Product) -> entities.Product:
        """Сохраняет новый товар, сразу отправляя INSERT в БД.

        Args:
            product: Товар без ``id``.

        Returns:
            Тот же объект с проставленным ``id``.
        """
        self.session.add(product)
        await self.session.flush()
        return product
