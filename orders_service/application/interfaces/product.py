"""Входящий порт сценариев товара."""

from abc import ABC, abstractmethod

from orders_service.application import dtos


class Product(ABC):
    """Сценарии товара — входящий порт.

    Контроллеры и декораторы зависят от этого порта, а не от ``services.Product``: так
    сценарий можно обернуть или подменить без правки сервиса.
    Контракт методов (аргументы, результат, ошибки) описан здесь; реализация описывает
    только особенности исполнения.
    """

    @abstractmethod
    async def add(self, new_product_info: dtos.NewProductInfo) -> dtos.Product:
        """Добавляет товар с начальным остатком.

        Args:
            new_product_info: Название, цена и начальный остаток.

        Returns:
            Добавленный товар с идентификатором.

        Raises:
            StorageUnavailable: Временный сбой хранилища.
        """

    @abstractmethod
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
