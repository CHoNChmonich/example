import uuid
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI

from orders_service.application import dtos, errors

# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
CUSTOMER = dtos.Customer(id=1, name="Иван", email="ivan@example.com")


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestRequestId:
    async def test__header_echoed(self, customer_service: Mock, client: httpx.AsyncClient) -> None:
        # Setup
        customer_service.get.return_value = CUSTOMER

        # Call
        response = await client.get("/api/v1/customers/1", headers={"X-Request-ID": "trace-1"})

        # Assert
        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == "trace-1"

    async def test__header_generated(
        self, customer_service: Mock, client: httpx.AsyncClient
    ) -> None:
        # Setup
        customer_service.get.return_value = CUSTOMER

        # Call
        response = await client.get("/api/v1/customers/1")

        # Assert
        assert uuid.UUID(response.headers["X-Request-ID"]).version == 4

    @pytest.mark.parametrize(
        "path, side_effect, status",
        [
            ("/api/v1/unknown", None, 404),
            ("/api/v1/customers/1", errors.StorageUnavailable(), 503),
            ("/api/v1/customers/1", RuntimeError("boom"), 500),
        ],
    )
    async def test__header_on_error_responses(
        self,
        path: str,
        side_effect: Exception | None,
        status: int,
        app: FastAPI,
        customer_service: Mock,
    ) -> None:
        # Setup: middleware стоит снаружи ServerErrorMiddleware, поэтому заголовок есть и у 500
        customer_service.get.side_effect = side_effect
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

        # Call
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(path, headers={"X-Request-ID": "trace-err"})

        # Assert
        assert response.status_code == status
        assert response.headers["X-Request-ID"] == "trace-err"
