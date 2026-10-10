"""Сценарии товара."""

from orders_service.application import dtos, entities, errors, interfaces


class Product:
    """Сценарии товара; каждый публичный метод — отдельная транзакция.

    Attributes:
        uow_factory: Вызываемый объект, создающий новый Unit of Work на каждый вызов метода.
    """

    def __init__(self, uow_factory: interfaces.UnitOfWorkFactory) -> None:
        """Принимает зависимости из composition root.

        Args:
            uow_factory: Фабрика Unit of Work — вызываемый объект без аргументов.
        """
        self.uow_factory = uow_factory

    async def add(self, new_product_info: dtos.NewProductInfo) -> dtos.Product:
        """Добавляет товар с начальным остатком.

        Args:
            new_product_info: Название, цена и начальный остаток.

        Returns:
            Добавленный товар с идентификатором.

        Raises:
            StorageUnavailable: Временный сбой хранилища.
        """
        async with self.uow_factory() as uow:
            product = entities.Product(
                name=new_product_info.name,
                price=new_product_info.price,
                stock=new_product_info.stock,
            )
            added = await uow.products.add(product)
            await uow.commit()
            return dtos.Product.model_validate(added)

    async def get(self, product_id: int) -> dtos.Product:
        """Возвращает товар по идентификатору.

        Args:
            product_id: Идентификатор товара.

        Returns:
            Найденный товар.

        Raises:
            ProductNotFound: Товара с таким идентификатором нет.
            StorageUnavailable: Временный сбой хранилища.
        """
        async with self.uow_factory() as uow:
            product = await uow.products.fetch_by_id(product_id)
            if product is None:
                raise errors.ProductNotFound(id=product_id)
            return dtos.Product.model_validate(product)
