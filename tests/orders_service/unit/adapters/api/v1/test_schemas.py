"""Шов HTTP ↔ ядро: тело, прошедшее ``*Body``, принимается DTO ядра.

Ограничения полей у ``*Body`` и ``dtos.New*Info`` — общие типы ``dtos.base``; тесты держат
это правило на граничных входах, чтобы расхождение не превратилось в 500 на ``to_application()``.
"""

from typing import Any

import pytest

from orders_service.adapters.api.v1 import schemas as api_schemas
from orders_service.application import dtos

# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
MAX_NAME = "и" * 255
MAX_EMAIL = "A" * 243 + "@EXAMPLE.COM"  # 255 символов ASCII: lower() длину не меняет


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestCustomerCreateBody:
    @pytest.mark.parametrize(
        "payload",
        [
            {"name": f"  {MAX_NAME}  ", "email": f"  {MAX_EMAIL}  "},
            {"name": "Иван", "email": "a@b.co"},
        ],
    )
    def test__edge_inputs_are_accepted_by_core(self, payload: dict[str, Any]) -> None:
        # Call
        info = api_schemas.CustomerCreateBody.model_validate(payload).to_application()

        # Assert
        assert len(info.name) <= 255
        assert len(info.email) <= 255
        assert info.email == info.email.lower()

    @pytest.mark.parametrize(
        "payload",
        [
            {"name": "и" * 256, "email": "a@b.co"},
            {"name": "Иван", "email": "A" * 244 + "@EXAMPLE.COM"},
            # «İ».lower() — два символа: 253 на входе стали бы 501 после нормализации.
            {"name": "Иван", "email": "İ" * 248 + "@x.yz"},
        ],
    )
    def test__rejected_at_the_edge(self, payload: dict[str, Any]) -> None:
        # Call and Assert
        with pytest.raises(ValueError):
            api_schemas.CustomerCreateBody.model_validate(payload)


class TestProductCreateBody:
    @pytest.mark.parametrize(
        "payload",
        [
            {"name": "Кружка", "price": "9999999999.99", "stock": dtos.MAX_INT32},
            {"name": "Кружка", "price": "0.01", "stock": 0},
        ],
    )
    def test__edge_inputs_are_accepted_by_core(self, payload: dict[str, Any]) -> None:
        # Call and Assert
        api_schemas.ProductCreateBody.model_validate(payload).to_application()

    @pytest.mark.parametrize(
        "payload",
        [
            {"name": "Кружка", "price": "1", "stock": 2**31},
            {"name": "Кружка", "price": "10000000000.00", "stock": 1},
        ],
    )
    def test__rejected_at_the_edge(self, payload: dict[str, Any]) -> None:
        # Call and Assert
        with pytest.raises(ValueError):
            api_schemas.ProductCreateBody.model_validate(payload)


class TestOrderCreateBody:
    def test__edge_inputs_are_accepted_by_core(self) -> None:
        # Setup
        payload = {
            "customer_id": dtos.MAX_INT32,
            "lines": [
                {"product_id": product_id, "quantity": dtos.MAX_LINE_QUANTITY}
                for product_id in range(1, dtos.MAX_ORDER_LINES + 1)
            ],
        }

        # Call
        info = api_schemas.OrderCreateBody.model_validate(payload).to_application()

        # Assert
        assert len(info.lines) == dtos.MAX_ORDER_LINES

    @pytest.mark.parametrize(
        "payload",
        [
            {"customer_id": 2**31, "lines": [{"product_id": 1, "quantity": 1}]},
            {
                "customer_id": 1,
                "lines": [{"product_id": 1, "quantity": dtos.MAX_LINE_QUANTITY + 1}],
            },
            {
                "customer_id": 1,
                "lines": [
                    {"product_id": product_id, "quantity": 1}
                    for product_id in range(1, dtos.MAX_ORDER_LINES + 2)
                ],
            },
            {
                "customer_id": 1,
                "lines": [{"product_id": 7, "quantity": 2}, {"product_id": 7, "quantity": 1}],
            },
        ],
    )
    def test__rejected_at_the_edge(self, payload: dict[str, Any]) -> None:
        # Call and Assert
        with pytest.raises(ValueError):
            api_schemas.OrderCreateBody.model_validate(payload)
