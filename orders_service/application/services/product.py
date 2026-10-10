"""Сценарии товара."""

from orders_service.application import dtos, entities, errors, interfaces
from orders_service.application.transactional import transactional


class Product:
    """Сценарии товара; каждый публичный метод — отдельная транзакция.

    Attributes:
        uow_factory: Фабрика Unit of Work, из которой обёртка берёт транзакцию на вызов.
    """

    def __init__(self, uow_factory: interfaces.UnitOfWorkFactory) -> None:
        """Принимает зависимости из composition root.

        Args:
            uow_factory: Фабрика Unit of Work.
        """
        self.uow_factory = uow_factory

    @transactional
    async def add(
        self, uow: interfaces.UnitOfWork, new_product_info: dtos.NewProductInfo
    ) -> dtos.Product:
        """Добавляет товар с начальным остатком.

        Args:
            uow: Транзакция, выданная обёрткой ``@transactional``.
            new_product_info: Название, цена и начальный остаток.

        Returns:
            Добавленный товар с идентификатором.

        Raises:
            StorageUnavailable: Временный сбой хранилища.
        """
        product = entities.Product(
            name=new_product_info.name,
            price=new_product_info.price,
            stock=new_product_info.stock,
        )
        added = await uow.products.add(product)
        return dtos.Product.model_validate(added)

    @transactional
    async def get(self, uow: interfaces.UnitOfWork, product_id: int) -> dtos.Product:
        """Возвращает товар по идентификатору.

        Args:
            uow: Транзакция, выданная обёрткой ``@transactional``.
            product_id: Идентификатор товара.

        Returns:
            Найденный товар.

        Raises:
            ProductNotFound: Товара с таким идентификатором нет.
            StorageUnavailable: Временный сбой хранилища.
        """
        product = await uow.products.fetch_by_id(product_id)
        if product is None:
            raise errors.ProductNotFound(id=product_id)
        return dtos.Product.model_validate(product)
