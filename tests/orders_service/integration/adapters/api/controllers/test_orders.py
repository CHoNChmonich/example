from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import Mock, call

import httpx
import pytest

from orders_service.application import dtos, entities, errors

# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
ORDER_LINE_1: dict[str, Any] = dict(
    id=1, product_id=7, quantity=2, unit_price=Decimal("10.00"), total=Decimal("20.00")
)
ORDER_1: dict[str, Any] = dict(
    id=100,
    customer_id=1,
    status=entities.OrderStatus.NEW,
    created_at=datetime(2026, 10, 10, 12, 0, tzinfo=UTC),
    lines=[dtos.OrderLine(**ORDER_LINE_1)],
    subtotal=Decimal("20.00"),
    discount=Decimal("1.00"),
    total=Decimal("19.00"),
)
ORDER_1_JSON: dict[str, Any] = dict(
    id=100,
    customer_id=1,
    status="new",
    created_at="2026-10-10T12:00:00Z",
    lines=[dict(id=1, product_id=7, quantity=2, unit_price="10.00", total="20.00")],
    subtotal="20.00",
    discount="1.00",
    total="19.00",
)
NEW_ORDER_BODY: dict[str, Any] = dict(customer_id=1, lines=[dict(product_id=7, quantity=2)])


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestPlaceOrder:
    async def test__place_order(self, order_service: Mock, client: httpx.AsyncClient) -> None:
        # Setup
        order_service.place.return_value = dtos.Order(**ORDER_1)

        # Call
        response = await client.post("/api/v1/orders", json=NEW_ORDER_BODY)

        # Assert
        assert response.status_code == 201
        assert response.json() == ORDER_1_JSON
        assert order_service.method_calls == [
            call.place(
                dtos.NewOrderInfo(
                    customer_id=1, lines=[dtos.NewOrderLineInfo(product_id=7, quantity=2)]
                )
            )
        ]

    async def test__zero_discount_has_two_decimals(
        self, order_service: Mock, client: httpx.AsyncClient
    ) -> None:
        # Setup: NoDiscount отдаёт Decimal("0"); до записи в БД это не "0.00", контракт держит шов
        order_service.place.return_value = dtos.Order(
            **{**ORDER_1, "discount": Decimal("0"), "total": Decimal("20")}
        )

        # Call
        response = await client.post("/api/v1/orders", json=NEW_ORDER_BODY)

        # Assert
        assert response.status_code == 201
        assert response.json()["discount"] == "0.00"
        assert response.json()["total"] == "20.00"

    async def test__duplicate_product(self, order_service: Mock, client: httpx.AsyncClient) -> None:
        # Call
        response = await client.post(
            "/api/v1/orders",
            json={
                "customer_id": 1,
                "lines": [{"product_id": 7, "quantity": 2}, {"product_id": 7, "quantity": 1}],
            },
        )

        # Assert
        assert response.status_code == 400
        details = response.json()["context"]["details"]
        assert details[0]["type"] == "order_duplicate_product"
        order_service.place.assert_not_called()

    @pytest.mark.parametrize(
        "payload",
        [
            {"customer_id": 99999999999, "lines": [{"product_id": 7, "quantity": 1}]},
            {"customer_id": 1, "lines": [{"product_id": 99999999999, "quantity": 1}]},
            {
                "customer_id": 1,
                "lines": [{"product_id": 7, "quantity": dtos.MAX_LINE_QUANTITY + 1}],
            },
        ],
    )
    async def test__values_outside_storage_range(
        self, payload: dict[str, object], order_service: Mock, client: httpx.AsyncClient
    ) -> None:
        # Call
        response = await client.post("/api/v1/orders", json=payload)

        # Assert
        assert response.status_code == 400
        assert response.json()["code"] == "validation_error"
        order_service.place.assert_not_called()

    async def test__insufficient_stock(
        self, order_service: Mock, client: httpx.AsyncClient
    ) -> None:
        # Setup
        order_service.place.side_effect = errors.InsufficientStock(
            product_id=7, requested=5, available=2
        )

        # Call
        response = await client.post(
            "/api/v1/orders", json={"customer_id": 1, "lines": [{"product_id": 7, "quantity": 5}]}
        )

        # Assert
        assert response.status_code == 400
        assert response.json() == {
            "error": "Товара 7 недостаточно: запрошено 5, доступно 2",
            "code": "insufficient_stock",
            "context": {"product_id": 7, "requested": 5, "available": 2},
        }

    async def test__customer_not_found(
        self, order_service: Mock, client: httpx.AsyncClient
    ) -> None:
        # Setup
        order_service.place.side_effect = errors.CustomerNotFound(id=1)

        # Call
        response = await client.post("/api/v1/orders", json=NEW_ORDER_BODY)

        # Assert
        assert response.status_code == 404
        assert response.json()["code"] == "customer_not_found"


class TestGetOrder:
    async def test__get_order(self, order_service: Mock, client: httpx.AsyncClient) -> None:
        # Setup
        order_service.get.return_value = dtos.Order(**ORDER_1)

        # Call
        response = await client.get("/api/v1/orders/100")

        # Assert
        assert response.status_code == 200
        assert response.json() == ORDER_1_JSON
        assert order_service.method_calls == [call.get(100)]

    async def test__order_not_found(self, order_service: Mock, client: httpx.AsyncClient) -> None:
        # Setup
        order_service.get.side_effect = errors.OrderNotFound(id=100)

        # Call
        response = await client.get("/api/v1/orders/100")

        # Assert
        assert response.status_code == 404
        assert response.json()["code"] == "order_not_found"


class TestListOrders:
    async def test__list_orders(self, order_service: Mock, client: httpx.AsyncClient) -> None:
        # Setup
        order_service.find.return_value = [dtos.Order(**ORDER_1)]
        filter_params = dtos.FindOrders(
            customer_id=1, status=entities.OrderStatus.PAID, limit=5, offset=10
        )

        # Call
        response = await client.get(
            "/api/v1/orders",
            params={"customer_id": 1, "status": "paid", "limit": 5, "offset": 10},
        )

        # Assert
        assert response.status_code == 200
        assert response.json() == {"items": [ORDER_1_JSON]}
        assert order_service.method_calls == [call.find(filter_params)]

    async def test__list_orders_default(
        self, order_service: Mock, client: httpx.AsyncClient
    ) -> None:
        # Setup
        order_service.find.return_value = []

        # Call
        response = await client.get("/api/v1/orders")

        # Assert
        assert response.status_code == 200
        assert response.json() == {"items": []}
        assert order_service.method_calls == [call.find(dtos.FindOrders())]

    @pytest.mark.parametrize(
        "params",
        [{"status": "shipped"}, {"customer_id": 99999999999}, {"limit": 201}, {"offset": 2**31}],
    )
    async def test__invalid_query(
        self, params: dict[str, str | int], order_service: Mock, client: httpx.AsyncClient
    ) -> None:
        # Call
        response = await client.get("/api/v1/orders", params=params)

        # Assert
        assert response.status_code == 400
        order_service.find.assert_not_called()


class TestPayOrder:
    async def test__pay_order(self, order_service: Mock, client: httpx.AsyncClient) -> None:
        # Setup
        order_service.pay.return_value = dtos.Order(
            **{**ORDER_1, "status": entities.OrderStatus.PAID}
        )

        # Call
        response = await client.post("/api/v1/orders/100/pay")

        # Assert
        assert response.status_code == 200
        assert response.json()["status"] == "paid"
        assert order_service.method_calls == [call.pay(100)]


class TestCancelOrder:
    async def test__cancel_order(self, order_service: Mock, client: httpx.AsyncClient) -> None:
        # Setup
        order_service.cancel.return_value = dtos.Order(
            **{**ORDER_1, "status": entities.OrderStatus.CANCELLED}
        )

        # Call
        response = await client.post("/api/v1/orders/100/cancel")

        # Assert
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        assert order_service.method_calls == [call.cancel(100)]

    async def test__transition_not_allowed(
        self, order_service: Mock, client: httpx.AsyncClient
    ) -> None:
        # Setup
        order_service.cancel.side_effect = errors.OrderTransitionNotAllowed(
            id=100, status=entities.OrderStatus.PAID, action="cancel"
        )

        # Call
        response = await client.post("/api/v1/orders/100/cancel")

        # Assert
        assert response.status_code == 400
        assert response.json() == {
            "error": "Заказ 100 в статусе paid: действие «cancel» недопустимо",
            "code": "order_transition_not_allowed",
            "context": {"id": 100, "status": "paid", "action": "cancel"},
        }
