"""Общие свойства HTTP-адаптера: 503, 500, 404/405, служебная ручка, контракт OpenAPI."""

import logging
from decimal import Decimal
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI

from orders_service.application import errors

# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
HANDLERS_LOGGER = "orders_service.adapters.api.error_handlers"


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestApplicationErrors:
    async def test__storage_unavailable(
        self, customer_service: Mock, client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Setup
        customer_service.get.side_effect = errors.StorageUnavailable()

        # Call
        with caplog.at_level(logging.WARNING, logger=HANDLERS_LOGGER):
            response = await client.get("/api/v1/customers/1")

        # Assert
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "1"
        assert response.json() == {
            "error": "Хранилище временно недоступно, повторите попытку",
            "code": "storage_unavailable",
            "context": {},
        }
        # Ожидаемый временный сбой: одно предупреждение без трассировки, не ERROR.
        records = [record for record in caplog.records if record.name == HANDLERS_LOGGER]
        assert [record.levelno for record in records] == [logging.WARNING]
        assert records[0].exc_info is None

    async def test__uncategorized_error_is_a_defect(
        self, customer_service: Mock, client: httpx.AsyncClient
    ) -> None:
        # Setup
        class Uncategorized(errors.Error):
            message_template = "ошибка без категории"

        customer_service.get.side_effect = Uncategorized()

        # Call
        response = await client.get("/api/v1/customers/1")

        # Assert
        assert response.status_code == 500
        assert response.json() == {
            "error": "Внутренняя ошибка сервера",
            "code": "uncategorized",
            "context": {},
        }

    async def test__decimal_in_context_is_a_string(
        self, customer_service: Mock, client: httpx.AsyncClient
    ) -> None:
        # Setup
        class PriceTooHigh(errors.RuleViolationError):
            message_template = "Слишком дорого: {price}"

        customer_service.get.side_effect = PriceTooHigh(price=Decimal("19.90"))

        # Call
        response = await client.get("/api/v1/customers/1")

        # Assert
        assert response.status_code == 400
        assert response.json()["context"] == {"price": "19.90"}


class TestUnexpectedError:
    async def test__unexpected_exception_without_details(
        self, app: FastAPI, customer_service: Mock
    ) -> None:
        # Setup
        customer_service.get.side_effect = RuntimeError("секрет не должен утечь")
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

        # Call
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/customers/1")

        # Assert
        assert response.status_code == 500
        assert response.json() == {
            "error": "Внутренняя ошибка сервера",
            "code": "internal_error",
            "context": {},
        }


class TestRouting:
    async def test__unknown_route(self, client: httpx.AsyncClient) -> None:
        # Call
        response = await client.get("/api/v1/nope")

        # Assert
        assert response.status_code == 404
        assert response.json() == {"error": "Not Found", "code": "http_error", "context": {}}

    async def test__method_not_allowed(self, client: httpx.AsyncClient) -> None:
        # Call
        response = await client.delete("/api/v1/customers/1")

        # Assert
        assert response.status_code == 405
        assert response.json()["code"] == "http_error"
        assert response.headers["Allow"] == "GET"  # заголовки Starlette сохраняются

    async def test__healthcheck(self, client: httpx.AsyncClient, app: FastAPI) -> None:
        # Call
        response = await client.get("/api/v1/healthcheck")

        # Assert
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert "/api/v1/healthcheck" not in app.openapi()["paths"]


class TestOpenApiContract:
    def test__operation_ids(self, app: FastAPI) -> None:
        # Call
        paths = app.openapi()["paths"]

        # Assert
        operation_ids = {
            operation["operationId"] for methods in paths.values() for operation in methods.values()
        }
        assert operation_ids == {
            "createCustomer",
            "getCustomerById",
            "createProduct",
            "getProductById",
            "placeOrder",
            "listOrders",
            "getOrderById",
            "payOrder",
            "cancelOrder",
        }

    def test__responses_without_422(self, app: FastAPI) -> None:
        # Call
        paths = app.openapi()["paths"]

        # Assert
        assert set(paths["/api/v1/orders"]["post"]["responses"]) == {
            "201",
            "400",
            "404",
            "500",
            "503",
        }
