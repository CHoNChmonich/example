from decimal import Decimal
from unittest.mock import ANY, MagicMock, Mock, call

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
    # Фабрика — вызываемый объект без аргументов; мок каждый раз отдаёт тот же UoW
    return Mock(return_value=uow)


@pytest.fixture(scope="function")
def service(uow_factory: Mock) -> services.Order:
    return services.Order(uow_factory=uow_factory, discount_policy=entities.NoDiscount())


@pytest.fixture(scope="function")
def service_with_volume_discount(uow_factory: Mock) -> services.Order:
    return services.Order(
        uow_factory=uow_factory,
        discount_policy=entities.VolumeDiscount(min_quantity=10, percent=Decimal("5")),
    )


def _assign_id(order: entities.Order) -> entities.Order:
    """Имитирует репозиторий: проставляет id заказу и строкам (мок хранит ссылку на объект)."""
    order.id = 100
    for index, line in enumerate(order.lines, start=1):
        line.id = index
        line.order_id = 100
    return order


def _products() -> list[entities.Product]:
    return [
        entities.Product(id=7, name="Кружка", price=Decimal("10.00"), stock=5),
        entities.Product(id=9, name="Ложка", price=Decimal("2.50"), stock=10),
    ]


def _stored_order(status: entities.OrderStatus = entities.OrderStatus.NEW) -> entities.Order:
    return entities.Order(
        id=100,
        customer_id=1,
        status=status,
        lines=[
            entities.OrderLine(
                id=1, order_id=100, product_id=7, quantity=2, unit_price=Decimal("10.00")
            )
        ],
    )


CUSTOMER = entities.Customer(id=1, name="Иван", email="ivan@example.com")
NEW_ORDER_INFO = dtos.NewOrderInfo(
    customer_id=1,
    lines=[
        dtos.NewOrderLineInfo(product_id=7, quantity=2),
        dtos.NewOrderLineInfo(product_id=9, quantity=8),
    ],
)


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestPlace:
    async def test__place(
        self, service_with_volume_discount: services.Order, uow: MagicMock
    ) -> None:
        # Setup
        products = _products()
        uow.customers.fetch_by_id.return_value = CUSTOMER
        uow.products.fetch_by_ids.return_value = products
        uow.orders.add.side_effect = _assign_id
        expected_order = entities.Order(
            id=100,
            customer_id=1,
            discount=Decimal("2.00"),  # 5 % от 40.00 за 10 единиц
            lines=[
                entities.OrderLine(
                    id=1, order_id=100, product_id=7, quantity=2, unit_price=Decimal("10.00")
                ),
                entities.OrderLine(
                    id=2, order_id=100, product_id=9, quantity=8, unit_price=Decimal("2.50")
                ),
            ],
        )

        # Call
        result = await service_with_volume_discount.place(NEW_ORDER_INFO)

        # Assert
        assert uow.mock_calls == [
            call.__aenter__(),
            call.customers.fetch_by_id(1),
            call.products.fetch_by_ids([7, 9], for_update=True),
            call.orders.add(expected_order),
            call.commit(),
            call.__aexit__(None, None, None),
        ]
        assert [product.stock for product in products] == [3, 2]
        assert result.model_dump(exclude={"created_at"}) == {
            "id": 100,
            "customer_id": 1,
            "status": entities.OrderStatus.NEW,
            "lines": [
                {
                    "id": 1,
                    "product_id": 7,
                    "quantity": 2,
                    "unit_price": Decimal("10.00"),
                    "total": Decimal("20.00"),
                },
                {
                    "id": 2,
                    "product_id": 9,
                    "quantity": 8,
                    "unit_price": Decimal("2.50"),
                    "total": Decimal("20.00"),
                },
            ],
            "subtotal": Decimal("40.00"),
            "discount": Decimal("2.00"),
            "total": Decimal("38.00"),
        }

    async def test__customer_not_found(self, service: services.Order, uow: MagicMock) -> None:
        # Setup
        uow.customers.fetch_by_id.return_value = None

        # Call and Assert
        with pytest.raises(errors.CustomerNotFound) as exc_info:
            await service.place(NEW_ORDER_INFO)

        assert exc_info.value.context == {"id": 1}
        uow.products.fetch_by_ids.assert_not_called()
        uow.commit.assert_not_called()

    async def test__product_not_found(self, service: services.Order, uow: MagicMock) -> None:
        # Setup
        uow.customers.fetch_by_id.return_value = CUSTOMER
        uow.products.fetch_by_ids.return_value = _products()[:1]  # товара 9 нет

        # Call and Assert
        with pytest.raises(errors.ProductNotFound) as exc_info:
            await service.place(NEW_ORDER_INFO)

        assert exc_info.value.context == {"id": 9}
        uow.orders.add.assert_not_called()
        uow.commit.assert_not_called()

    async def test__insufficient_stock(self, service: services.Order, uow: MagicMock) -> None:
        # Setup
        products = _products()
        products[1].stock = 7  # меньше запрошенных 8
        uow.customers.fetch_by_id.return_value = CUSTOMER
        uow.products.fetch_by_ids.return_value = products

        # Call and Assert
        with pytest.raises(errors.InsufficientStock) as exc_info:
            await service.place(NEW_ORDER_INFO)

        assert exc_info.value.context == {"product_id": 9, "requested": 8, "available": 7}
        uow.orders.add.assert_not_called()
        uow.commit.assert_not_called()
        uow.__aexit__.assert_called_once_with(errors.InsufficientStock, exc_info.value, ANY)


class TestGet:
    @pytest.mark.parametrize("repo_output", [_stored_order()])
    async def test__get(
        self, repo_output: entities.Order, service: services.Order, uow: MagicMock
    ) -> None:
        # Setup
        uow.orders.fetch_by_id.return_value = repo_output

        # Call
        result = await service.get(100)

        # Assert
        assert uow.mock_calls == [
            call.__aenter__(),
            call.orders.fetch_by_id(100),
            call.__aexit__(None, None, None),
        ]
        assert result.id == 100
        assert result.total == Decimal("20.00")

    async def test__order_not_found(self, service: services.Order, uow: MagicMock) -> None:
        # Setup
        uow.orders.fetch_by_id.return_value = None

        # Call and Assert
        with pytest.raises(errors.OrderNotFound) as exc_info:
            await service.get(100)

        assert exc_info.value.context == {"id": 100}


class TestFind:
    @pytest.mark.parametrize(
        "repo_output, expected_statuses",
        [
            (
                [_stored_order(), _stored_order(entities.OrderStatus.PAID)],
                [entities.OrderStatus.NEW, entities.OrderStatus.PAID],
            ),
            ([], []),
        ],
    )
    async def test__find(
        self,
        repo_output: list[entities.Order],
        expected_statuses: list[entities.OrderStatus],
        service: services.Order,
        uow: MagicMock,
    ) -> None:
        # Setup
        uow.orders.fetch_all.return_value = repo_output
        filter_params = dtos.FindOrders(customer_id=1, limit=5)

        # Call
        result = await service.find(filter_params)

        # Assert
        assert uow.mock_calls == [
            call.__aenter__(),
            call.orders.fetch_all(filter_params),
            call.__aexit__(None, None, None),
        ]
        assert [order.status for order in result] == expected_statuses


class TestPay:
    async def test__pay(self, service: services.Order, uow: MagicMock) -> None:
        # Setup
        uow.orders.fetch_by_id.return_value = _stored_order()

        # Call
        result = await service.pay(100)

        # Assert
        assert uow.mock_calls == [
            call.__aenter__(),
            call.orders.fetch_by_id(100, for_update=True),
            call.commit(),
            call.__aexit__(None, None, None),
        ]
        assert result.status is entities.OrderStatus.PAID

    async def test__order_already_paid(self, service: services.Order, uow: MagicMock) -> None:
        # Setup
        uow.orders.fetch_by_id.return_value = _stored_order(entities.OrderStatus.PAID)

        # Call and Assert
        with pytest.raises(errors.OrderTransitionNotAllowed) as exc_info:
            await service.pay(100)

        assert exc_info.value.context == {
            "id": 100,
            "status": entities.OrderStatus.PAID,
            "action": "pay",
        }
        uow.commit.assert_not_called()

    async def test__order_not_found(self, service: services.Order, uow: MagicMock) -> None:
        # Setup
        uow.orders.fetch_by_id.return_value = None

        # Call and Assert
        with pytest.raises(errors.OrderNotFound):
            await service.pay(100)

        uow.commit.assert_not_called()


class TestCancel:
    async def test__cancel(self, service: services.Order, uow: MagicMock) -> None:
        # Setup
        product = entities.Product(id=7, name="Кружка", price=Decimal("10.00"), stock=3)
        uow.orders.fetch_by_id.return_value = _stored_order()
        uow.products.fetch_by_ids.return_value = [product]

        # Call
        result = await service.cancel(100)

        # Assert
        assert uow.mock_calls == [
            call.__aenter__(),
            call.orders.fetch_by_id(100, for_update=True),
            call.products.fetch_by_ids([7], for_update=True),
            call.commit(),
            call.__aexit__(None, None, None),
        ]
        assert result.status is entities.OrderStatus.CANCELLED
        assert product.stock == 5

    async def test__order_already_paid(self, service: services.Order, uow: MagicMock) -> None:
        # Setup
        uow.orders.fetch_by_id.return_value = _stored_order(entities.OrderStatus.PAID)

        # Call and Assert
        with pytest.raises(errors.OrderTransitionNotAllowed):
            await service.cancel(100)

        uow.products.fetch_by_ids.assert_not_called()
        uow.commit.assert_not_called()

    async def test__order_not_found(self, service: services.Order, uow: MagicMock) -> None:
        # Setup
        uow.orders.fetch_by_id.return_value = None

        # Call and Assert
        with pytest.raises(errors.OrderNotFound):
            await service.cancel(100)

        uow.commit.assert_not_called()
