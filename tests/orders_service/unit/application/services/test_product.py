from decimal import Decimal
from unittest.mock import MagicMock, Mock, call

import pytest

from orders_service.application import dtos, entities, errors, interfaces, services


# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
@pytest.fixture(scope="function")
def uow() -> MagicMock:
    unit_of_work = MagicMock(spec=interfaces.UnitOfWork)
    unit_of_work.__aenter__.return_value = unit_of_work
    unit_of_work.customers = Mock(interfaces.CustomersRepo)
    unit_of_work.products = Mock(interfaces.ProductsRepo)
    unit_of_work.orders = Mock(interfaces.OrdersRepo)
    return unit_of_work


@pytest.fixture(scope="function")
def uow_factory(uow: MagicMock) -> Mock:
    factory = Mock(interfaces.UnitOfWorkFactory)
    factory.create.return_value = uow
    return factory


@pytest.fixture(scope="function")
def service(uow_factory: Mock) -> services.Product:
    return services.Product(uow_factory=uow_factory)


def _assign_id(product: entities.Product) -> entities.Product:
    """Имитирует репозиторий: проставляет id переданному объекту (мок хранит ссылку на него)."""
    product.id = 7
    return product


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestAdd:
    @pytest.mark.parametrize(
        "input_dto, repo_output, service_output",
        [
            (
                dtos.NewProductInfo(name="Кружка", price=Decimal("10.00"), stock=5),
                entities.Product(id=7, name="Кружка", price=Decimal("10.00"), stock=5),
                dtos.Product(id=7, name="Кружка", price=Decimal("10.00"), stock=5),
            )
        ],
    )
    async def test__add(
        self,
        input_dto: dtos.NewProductInfo,
        repo_output: entities.Product,
        service_output: dtos.Product,
        service: services.Product,
        uow: MagicMock,
    ) -> None:
        # Setup
        uow.products.add.side_effect = _assign_id

        # Call
        result = await service.add(input_dto)

        # Assert
        assert uow.mock_calls == [
            call.__aenter__(),
            call.products.add(repo_output),
            call.commit(),
            call.__aexit__(None, None, None),
        ]
        assert result == service_output


class TestGet:
    @pytest.mark.parametrize(
        "repo_output, service_output",
        [
            (
                entities.Product(id=7, name="Кружка", price=Decimal("10.00"), stock=5),
                dtos.Product(id=7, name="Кружка", price=Decimal("10.00"), stock=5),
            )
        ],
    )
    async def test__get(
        self,
        repo_output: entities.Product,
        service_output: dtos.Product,
        service: services.Product,
        uow: MagicMock,
    ) -> None:
        # Setup
        uow.products.fetch_by_id.return_value = repo_output

        # Call
        result = await service.get(service_output.id)

        # Assert
        assert uow.products.method_calls == [call.fetch_by_id(service_output.id)]
        assert result == service_output

    async def test__product_not_found(self, service: services.Product, uow: MagicMock) -> None:
        # Setup
        uow.products.fetch_by_id.return_value = None

        # Call and Assert
        with pytest.raises(errors.ProductNotFound) as exc_info:
            await service.get(42)

        assert exc_info.value.context == {"id": 42}
        assert uow.products.method_calls == [call.fetch_by_id(42)]
