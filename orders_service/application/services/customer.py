"""Сценарии клиента."""

from orders_service.application import dtos, entities, errors, interfaces


class Customer(interfaces.Customer):
    """Сценарии клиента; каждый публичный метод — отдельная транзакция.

    Контракт методов — у порта ``interfaces.Customer``; здесь — как он исполняется.

    Attributes:
        uow_factory: Вызываемый объект, создающий новый Unit of Work на каждый вызов метода.
    """

    def __init__(self, uow_factory: interfaces.UnitOfWorkFactory) -> None:
        """Принимает зависимости из composition root.

        Args:
            uow_factory: Фабрика Unit of Work — вызываемый объект без аргументов.
        """
        self.uow_factory = uow_factory

    async def add(self, new_customer_info: dtos.NewCustomerInfo) -> dtos.Customer:
        """Регистрирует клиента: предварительная проверка email, затем запись и commit.

        Args:
            new_customer_info: Имя и email нового клиента.

        Returns:
            Зарегистрированный клиент с идентификатором.
        """
        async with self.uow_factory() as uow:
            if await uow.customers.fetch_by_email(new_customer_info.email) is not None:
                raise errors.CustomerAlreadyExists(email=new_customer_info.email)
            customer = entities.Customer(name=new_customer_info.name, email=new_customer_info.email)
            added = await uow.customers.add(customer)
            await uow.commit()
            return dtos.Customer.model_validate(added)

    async def get(self, customer_id: int) -> dtos.Customer:
        """Возвращает клиента по идентификатору; чтение без commit.

        Args:
            customer_id: Идентификатор клиента.

        Returns:
            Найденный клиент.
        """
        async with self.uow_factory() as uow:
            customer = await uow.customers.fetch_by_id(customer_id)
            if customer is None:
                raise errors.CustomerNotFound(id=customer_id)
            return dtos.Customer.model_validate(customer)
