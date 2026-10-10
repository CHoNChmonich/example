from decimal import Decimal
from typing import Any
from unittest.mock import Mock, call

import httpx
import pytest

from orders_service.application import dtos, errors

# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
PRODUCT_1: dict[str, Any] = dict(id=7, name="Кружка", price=Decimal("19.99"), stock=100)
PRODUCT_1_JSON: dict[str, Any] = dict(id=7, name="Кружка", price="19.99", stock=100)


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestCreateProduct:
    async def test__create_product(self, product_service: Mock, client: httpx.AsyncClient) -> None:
        # Setup
        product_service.add.return_value = dtos.Product(**PRODUCT_1)

        # Call
        response = await client.post(
            "/api/v1/products", json={"name": "Кружка", "price": "19.99", "stock": 100}
        )

        # Assert
        assert response.status_code == 201
        assert response.json() == PRODUCT_1_JSON  # деньги — строкой с двумя знаками
        assert product_service.method_calls == [
            call.add(dtos.NewProductInfo(name="Кружка", price=Decimal("19.99"), stock=100))
        ]

    async def test__money_has_two_decimals(
        self, product_service: Mock, client: httpx.AsyncClient
    ) -> None:
        # Setup: значение, не прошедшее через БД (Decimal("10")), сериализуется как после неё
        product_service.add.return_value = dtos.Product(**{**PRODUCT_1, "price": Decimal("10")})

        # Call
        response = await client.post(
            "/api/v1/products", json={"name": "Кружка", "price": "10", "stock": 100}
        )

        # Assert
        assert response.status_code == 201
        assert response.json()["price"] == "10.00"

    @pytest.mark.parametrize(
        "payload",
        [
            {"name": "Кружка", "price": "0", "stock": 1},
            {"name": "Кружка", "price": "1.234", "stock": 1},
            {"name": "Кружка", "price": "1", "stock": 3_000_000_000},
        ],
    )
    async def test__invalid_body(
        self, payload: dict[str, object], product_service: Mock, client: httpx.AsyncClient
    ) -> None:
        # Call
        response = await client.post("/api/v1/products", json=payload)

        # Assert
        assert response.status_code == 400
        assert response.json()["code"] == "validation_error"
        product_service.add.assert_not_called()


class TestGetProduct:
    async def test__get_product(self, product_service: Mock, client: httpx.AsyncClient) -> None:
        # Setup
        returned_product = dtos.Product(**PRODUCT_1)
        product_service.get.return_value = returned_product

        # Call
        response = await client.get(f"/api/v1/products/{returned_product.id}")

        # Assert
        assert response.status_code == 200
        assert response.json() == PRODUCT_1_JSON
        assert product_service.method_calls == [call.get(returned_product.id)]

    async def test__product_not_found(
        self, product_service: Mock, client: httpx.AsyncClient
    ) -> None:
        # Setup
        product_service.get.side_effect = errors.ProductNotFound(id=42)

        # Call
        response = await client.get("/api/v1/products/42")

        # Assert
        assert response.status_code == 404
        assert response.json()["code"] == "product_not_found"
