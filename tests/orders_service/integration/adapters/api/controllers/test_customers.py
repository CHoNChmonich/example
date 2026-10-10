from typing import Any
from unittest.mock import Mock, call

import httpx

from orders_service.application import dtos, errors

# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
CUSTOMER_1: dict[str, Any] = dict(id=1, name="Иван Петров", email="ivan@example.com")


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestCreateCustomer:
    async def test__create_customer(
        self, customer_service: Mock, client: httpx.AsyncClient
    ) -> None:
        # Setup
        returned_customer = dtos.Customer(**CUSTOMER_1)
        customer_service.add.return_value = returned_customer

        # Call
        response = await client.post(
            "/api/v1/customers", json={"name": " Иван Петров ", "email": "Ivan@Example.com"}
        )

        # Assert
        assert response.status_code == 201
        assert response.json() == CUSTOMER_1
        assert customer_service.method_calls == [
            call.add(dtos.NewCustomerInfo(name="Иван Петров", email="ivan@example.com"))
        ]

    async def test__customer_already_exists(
        self, customer_service: Mock, client: httpx.AsyncClient
    ) -> None:
        # Setup
        customer_service.add.side_effect = errors.CustomerAlreadyExists(email="ivan@example.com")

        # Call
        response = await client.post(
            "/api/v1/customers", json={"name": "Иван", "email": "ivan@example.com"}
        )

        # Assert
        assert response.status_code == 409
        assert response.json() == {
            "error": "Клиент с email ivan@example.com уже существует",
            "code": "customer_already_exists",
            "context": {"email": "ivan@example.com"},
        }

    async def test__invalid_body(self, customer_service: Mock, client: httpx.AsyncClient) -> None:
        # Call
        response = await client.post(
            "/api/v1/customers", json={"name": "", "email": "not-an-email"}
        )

        # Assert
        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "validation_error"
        assert body["error"] == "Некорректный запрос"
        assert {tuple(detail["loc"]) for detail in body["context"]["details"]} == {
            ("body", "name"),
            ("body", "email"),
        }
        customer_service.add.assert_not_called()

    async def test__non_ascii_email(
        self, customer_service: Mock, client: httpx.AsyncClient
    ) -> None:
        # Call
        response = await client.post(
            "/api/v1/customers", json={"name": "Иван", "email": "İ" * 248 + "@x.yz"}
        )

        # Assert
        assert response.status_code == 400
        assert response.json()["code"] == "validation_error"
        customer_service.add.assert_not_called()

    async def test__unknown_field(self, client: httpx.AsyncClient) -> None:
        # Call
        response = await client.post(
            "/api/v1/customers",
            json={"name": "Иван", "email": "ivan@example.com", "id": 5},
        )

        # Assert
        assert response.status_code == 400


class TestGetCustomer:
    async def test__get_customer(self, customer_service: Mock, client: httpx.AsyncClient) -> None:
        # Setup
        returned_customer = dtos.Customer(**CUSTOMER_1)
        customer_service.get.return_value = returned_customer

        # Call
        response = await client.get(f"/api/v1/customers/{returned_customer.id}")

        # Assert
        assert response.status_code == 200
        assert response.json() == CUSTOMER_1
        assert customer_service.method_calls == [call.get(returned_customer.id)]

    async def test__customer_not_found(
        self, customer_service: Mock, client: httpx.AsyncClient
    ) -> None:
        # Setup
        customer_service.get.side_effect = errors.CustomerNotFound(id=42)

        # Call
        response = await client.get("/api/v1/customers/42")

        # Assert
        assert response.status_code == 404
        assert response.json() == {
            "error": "Клиент с id 42 не найден",
            "code": "customer_not_found",
            "context": {"id": 42},
        }

    async def test__id_outside_storage_range(
        self, customer_service: Mock, client: httpx.AsyncClient
    ) -> None:
        # Call
        responses = [
            await client.get(f"/api/v1/customers/{bad_id}") for bad_id in ("0", "99999999999")
        ]

        # Assert
        assert [response.status_code for response in responses] == [400, 400]
        customer_service.get.assert_not_called()
