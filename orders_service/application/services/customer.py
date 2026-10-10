"""Сценарии клиента."""

from orders_service.application import dtos, entities, errors, interfaces
from orders_service.application.transactional import transactional


class Customer:
    """Сценарии клиента; каждый публичный метод — отдельная транзакция.

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
        self, uow: interfaces.UnitOfWork, new_customer_info: dtos.NewCustomerInfo
    ) -> dtos.Customer:
        """Регистрирует клиента.

        Args:
            uow: Транзакция, выданная обёрткой ``@transactional``.
            new_customer_info: Имя и email нового клиента.

        Returns:
            Зарегистрированный клиент с идентификатором.

        Raises:
            CustomerAlreadyExists: Email уже занят — по предварительной проверке либо по
                ограничению уникальности хранилища при одновременной регистрации.
            StorageUnavailable: Временный сбой хранилища.
        """
        if await uow.customers.fetch_by_email(new_customer_info.email) is not None:
            raise errors.CustomerAlreadyExists(email=new_customer_info.email)
        customer = entities.Customer(name=new_customer_info.name, email=new_customer_info.email)
        added = await uow.customers.add(customer)
        return dtos.Customer.model_validate(added)

    @transactional
    async def get(self, uow: interfaces.UnitOfWork, customer_id: int) -> dtos.Customer:
        """Возвращает клиента по идентификатору.

        Args:
            uow: Транзакция, выданная обёрткой ``@transactional``.
            customer_id: Идентификатор клиента.

        Returns:
            Найденный клиент.

        Raises:
            CustomerNotFound: Клиента с таким идентификатором нет.
            StorageUnavailable: Временный сбой хранилища.
        """
        customer = await uow.customers.fetch_by_id(customer_id)
        if customer is None:
            raise errors.CustomerNotFound(id=customer_id)
        return dtos.Customer.model_validate(customer)
