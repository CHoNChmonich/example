"""Входящий порт сценариев клиента."""

from abc import ABC, abstractmethod

from orders_service.application import dtos


class Customer(ABC):
    """Сценарии клиента — входящий порт.

    Контроллеры и декораторы зависят от этого порта, а не от ``services.Customer``: так
    сценарий можно обернуть или подменить без правки сервиса.
    Контракт методов (аргументы, результат, ошибки) описан здесь; реализация описывает
    только особенности исполнения.
    """

    @abstractmethod
    async def add(self, new_customer_info: dtos.NewCustomerInfo) -> dtos.Customer:
        """Регистрирует клиента.

        Args:
            new_customer_info: Имя и email нового клиента.

        Returns:
            Зарегистрированный клиент с идентификатором.

        Raises:
            CustomerAlreadyExists: Email уже занят — по предварительной проверке либо по
                ограничению уникальности хранилища при одновременной регистрации.
            StorageUnavailable: Временный сбой хранилища.
        """

    @abstractmethod
    async def get(self, customer_id: int) -> dtos.Customer:
        """Возвращает клиента по идентификатору.

        Args:
            customer_id: Идентификатор клиента.

        Returns:
            Найденный клиент.

        Raises:
            CustomerNotFound: Клиента с таким идентификатором нет.
            StorageUnavailable: Временный сбой хранилища.
        """
