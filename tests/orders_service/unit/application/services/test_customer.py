from unittest.mock import MagicMock, Mock, call

import pytest

from orders_service.application import dtos, entities, errors, interfaces, services


# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
@pytest.fixture(scope="function")
def uow() -> MagicMock:
    # MagicMock по spec порта работает как async-контекст и не глотает исключения, но
    # ``__aenter__`` по умолчанию отдаёт другой объект, а spec не протаскивается
    # в свойства-репозитории — то и другое задаётся явно.
    unit_of_work = MagicMock(spec=interfaces.UnitOfWork)
    unit_of_work.__aenter__.return_value = unit_of_work
    unit_of_work.customers = Mock(interfaces.CustomersRepo)
    unit_of_work.products = Mock(interfaces.ProductsRepo)
    unit_of_work.orders = Mock(interfaces.OrdersRepo)
    return unit_of_work


@pytest.fixture(scope="function")
def uow_factory(uow: MagicMock) -> Mock:
    # Фабрика — вызываемый объект без аргументов; мок каждый раз отдаёт тот же UoW
    return Mock(return_value=uow)


@pytest.fixture(scope="function")
def service(uow_factory: Mock) -> services.Customer:
    return services.Customer(uow_factory=uow_factory)


def _assign_id(customer: entities.Customer) -> entities.Customer:
    """Имитирует репозиторий: проставляет id переданному объекту (мок хранит ссылку на него)."""
    customer.id = 1
    return customer


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestAdd:
    @pytest.mark.parametrize(
        "input_dto, repo_output, service_output",
        [
            (
                dtos.NewCustomerInfo(name="Иван", email="ivan@example.com"),
                entities.Customer(id=1, name="Иван", email="ivan@example.com"),
                dtos.Customer(id=1, name="Иван", email="ivan@example.com"),
            )
        ],
    )
    async def test__add(
        self,
        input_dto: dtos.NewCustomerInfo,
        repo_output: entities.Customer,
        service_output: dtos.Customer,
        service: services.Customer,
        uow: MagicMock,
    ) -> None:
        # Setup
        uow.customers.fetch_by_email.return_value = None
        uow.customers.add.side_effect = _assign_id

        # Call
        result = await service.add(input_dto)

        # Assert
        assert uow.mock_calls == [
            call.__aenter__(),
            call.customers.fetch_by_email(input_dto.email),
            call.customers.add(repo_output),
            call.commit(),
            call.__aexit__(None, None, None),
        ]
        assert result == service_output

    @pytest.mark.parametrize(
        "input_dto, repo_output",
        [
            (
                dtos.NewCustomerInfo(name="Иван", email="ivan@example.com"),
                entities.Customer(id=1, name="Другой Иван", email="ivan@example.com"),
            )
        ],
    )
    async def test__customer_already_exists(
        self,
        input_dto: dtos.NewCustomerInfo,
        repo_output: entities.Customer,
        service: services.Customer,
        uow: MagicMock,
    ) -> None:
        # Setup
        uow.customers.fetch_by_email.return_value = repo_output

        # Call and Assert
        with pytest.raises(errors.CustomerAlreadyExists) as exc_info:
            await service.add(input_dto)

        assert exc_info.value.context == {"email": input_dto.email}
        assert uow.customers.method_calls == [call.fetch_by_email(input_dto.email)]
        uow.commit.assert_not_called()


class TestGet:
    @pytest.mark.parametrize(
        "repo_output, service_output",
        [
            (
                entities.Customer(id=1, name="Иван", email="ivan@example.com"),
                dtos.Customer(id=1, name="Иван", email="ivan@example.com"),
            )
        ],
    )
    async def test__get(
        self,
        repo_output: entities.Customer,
        service_output: dtos.Customer,
        service: services.Customer,
        uow: MagicMock,
    ) -> None:
        # Setup
        uow.customers.fetch_by_id.return_value = repo_output

        # Call
        result = await service.get(service_output.id)

        # Assert
        assert uow.mock_calls == [
            call.__aenter__(),
            call.customers.fetch_by_id(service_output.id),
            call.__aexit__(None, None, None),
        ]
        assert result == service_output

    async def test__customer_not_found(self, service: services.Customer, uow: MagicMock) -> None:
        # Setup
        uow.customers.fetch_by_id.return_value = None

        # Call and Assert
        with pytest.raises(errors.CustomerNotFound) as exc_info:
            await service.get(42)

        assert exc_info.value.context == {"id": 42}
        assert uow.customers.method_calls == [call.fetch_by_id(42)]

    async def test__new_unit_of_work_per_call(
        self, service: services.Customer, uow: MagicMock, uow_factory: Mock
    ) -> None:
        # Setup
        uow.customers.fetch_by_id.return_value = entities.Customer(
            id=1, name="Иван", email="ivan@example.com"
        )

        # Call
        await service.get(1)
        await service.get(1)

        # Assert
        assert uow_factory.call_count == 2
        assert uow.mock_calls == [
            call.__aenter__(),
            call.customers.fetch_by_id(1),
            call.__aexit__(None, None, None),
            call.__aenter__(),
            call.customers.fetch_by_id(1),
            call.__aexit__(None, None, None),
        ]
