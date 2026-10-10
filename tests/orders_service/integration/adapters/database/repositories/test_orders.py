from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orders_service.adapters.database import repositories, tables
from orders_service.application import dtos, entities

from .. import test_data


# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
@pytest.fixture(scope="function", autouse=True)
async def fill_db(session: AsyncSession) -> dict[str, list[int]]:
    customer_ids: list[int] = await test_data.insert_customers(session)
    product_ids: list[int] = await test_data.insert_products(session)
    order_ids: list[int] = await test_data.insert_orders(customer_ids, session)
    line_ids: list[int] = await test_data.insert_order_lines(order_ids, product_ids, session)
    return {
        "customer_ids": customer_ids,
        "product_ids": product_ids,
        "order_ids": order_ids,
        "line_ids": line_ids,
    }


@pytest.fixture(scope="function")
def repo(session: AsyncSession) -> repositories.OrdersRepo:
    return repositories.OrdersRepo(session)


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestFetchById:
    async def test__fetch_by_id(
        self, repo: repositories.OrdersRepo, fill_db: dict[str, list[int]]
    ) -> None:
        # Setup
        order_id: int = fill_db["order_ids"][0]
        # Строки раздаются заказам по кругу: первому заказу достались 1-я и 5-я
        expected_lines = [test_data.ORDER_LINES_DATA[0], test_data.ORDER_LINES_DATA[4]]

        # Call
        result = await repo.fetch_by_id(order_id)

        # Assert
        assert isinstance(result, entities.Order)
        assert result.id == order_id
        assert result.status is entities.OrderStatus.NEW
        assert [(line.quantity, line.unit_price) for line in result.lines] == [
            (line["quantity"], line["unit_price"]) for line in expected_lines
        ]
        assert result.total == Decimal("30.00")

    async def test__order_not_found(
        self, repo: repositories.OrdersRepo, fill_db: dict[str, list[int]]
    ) -> None:
        # Call
        result = await repo.fetch_by_id(max(fill_db["order_ids"]) + 1)

        # Assert
        assert result is None


class TestFetchAll:
    async def test__fetch_all(
        self, repo: repositories.OrdersRepo, fill_db: dict[str, list[int]]
    ) -> None:
        # Setup
        filter_params = dtos.FindOrders()

        # Call
        result = await repo.fetch_all(filter_params)

        # Assert
        assert len(result) == len(test_data.ORDERS_DATA)
        assert all(isinstance(order, entities.Order) for order in result)

    async def test__by_customer(
        self, repo: repositories.OrdersRepo, fill_db: dict[str, list[int]]
    ) -> None:
        # Setup: заказы раздаются клиентам по кругу — первому достались 1-й и 4-й
        customer_id: int = fill_db["customer_ids"][0]
        filter_params = dtos.FindOrders(customer_id=customer_id)

        # Call
        result = await repo.fetch_all(filter_params)

        # Assert
        assert [order.id for order in result] == [fill_db["order_ids"][0], fill_db["order_ids"][3]]
        assert all(order.customer_id == customer_id for order in result)

    @pytest.mark.parametrize(
        "status, expected_count",
        [
            (entities.OrderStatus.NEW, 2),
            (entities.OrderStatus.PAID, 1),
            (entities.OrderStatus.CANCELLED, 1),
        ],
    )
    async def test__by_status(
        self,
        status: entities.OrderStatus,
        expected_count: int,
        repo: repositories.OrdersRepo,
    ) -> None:
        # Setup
        filter_params = dtos.FindOrders(status=status)

        # Call
        result = await repo.fetch_all(filter_params)

        # Assert
        assert len(result) == expected_count
        assert all(order.status is status for order in result)

    async def test__order_is_asc_by_id(
        self, repo: repositories.OrdersRepo, fill_db: dict[str, list[int]]
    ) -> None:
        # Setup
        filter_params = dtos.FindOrders()

        # Call
        result = await repo.fetch_all(filter_params)

        # Assert
        assert [order.id for order in result] == sorted(fill_db["order_ids"])

    async def test__with_limit(self, repo: repositories.OrdersRepo) -> None:
        # Setup
        filter_params = dtos.FindOrders(limit=1)

        # Call
        result = await repo.fetch_all(filter_params)

        # Assert
        assert len(result) == filter_params.limit

    async def test__with_offset(self, repo: repositories.OrdersRepo) -> None:
        # Setup
        filter_params = dtos.FindOrders(offset=1)

        # Call
        result = await repo.fetch_all(filter_params)

        # Assert
        assert len(result) == len(test_data.ORDERS_DATA) - filter_params.offset


class TestAdd:
    async def test__add(
        self,
        repo: repositories.OrdersRepo,
        session: AsyncSession,
        fill_db: dict[str, list[int]],
    ) -> None:
        # Setup
        before_orders = await test_data.count_rows(tables.orders, session)
        before_lines = await test_data.count_rows(tables.order_lines, session)
        order = entities.Order(
            customer_id=fill_db["customer_ids"][0],
            lines=[
                entities.OrderLine(
                    product_id=fill_db["product_ids"][0], quantity=1, unit_price=Decimal("10.00")
                ),
                entities.OrderLine(
                    product_id=fill_db["product_ids"][1], quantity=2, unit_price=Decimal("2.50")
                ),
            ],
        )

        # Call
        result = await repo.add(order)

        # Setup
        after_orders = await test_data.count_rows(tables.orders, session)
        after_lines = await test_data.count_rows(tables.order_lines, session)

        # Assert
        assert before_orders + 1 == after_orders
        assert before_lines + 2 == after_lines  # строки сохраняются каскадом
        assert isinstance(result, entities.Order)
        assert result.id is not None
        assert all(line.order_id == result.id for line in result.lines)
