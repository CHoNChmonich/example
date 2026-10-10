from decimal import Decimal

import pytest

from orders_service.application import dtos


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestNewCustomerInfo:
    def test__normalizes_input(self) -> None:
        # Call
        info = dtos.NewCustomerInfo(name="  Иван ", email=" Ivan@Example.com ")

        # Assert
        assert info.name == "Иван"
        assert info.email == "ivan@example.com"

    @pytest.mark.parametrize("email", ["not-an-email", "иван@пример.рф", "a@b", ""])
    def test__bad_email(self, email: str) -> None:
        # Call and Assert
        with pytest.raises(ValueError, match="email"):
            dtos.NewCustomerInfo(name="Иван", email=email)


class TestNewProductInfo:
    @pytest.mark.parametrize("price", [Decimal("0"), Decimal("-1"), Decimal("1.234")])
    def test__bad_price(self, price: Decimal) -> None:
        # Call and Assert
        with pytest.raises(ValueError, match="price"):
            dtos.NewProductInfo(name="Кружка", price=price, stock=1)

    @pytest.mark.parametrize("stock", [-1, dtos.MAX_INT32 + 1])
    def test__stock_outside_storage_range(self, stock: int) -> None:
        # Call and Assert
        with pytest.raises(ValueError, match="stock"):
            dtos.NewProductInfo(name="Кружка", price=Decimal("1.00"), stock=stock)


class TestNewOrderInfo:
    def test__duplicate_products(self) -> None:
        # Call and Assert
        with pytest.raises(ValueError, match="одной строкой"):
            dtos.NewOrderInfo(
                customer_id=1,
                lines=[
                    dtos.NewOrderLineInfo(product_id=7, quantity=1),
                    dtos.NewOrderLineInfo(product_id=7, quantity=2),
                ],
            )

    def test__empty_lines(self) -> None:
        # Call and Assert
        with pytest.raises(ValueError, match="lines"):
            dtos.NewOrderInfo(customer_id=1, lines=[])

    def test__too_many_lines(self) -> None:
        # Setup
        lines = [
            dtos.NewOrderLineInfo(product_id=product_id, quantity=1)
            for product_id in range(1, dtos.MAX_ORDER_LINES + 2)
        ]

        # Call and Assert
        with pytest.raises(ValueError, match="lines"):
            dtos.NewOrderInfo(customer_id=1, lines=lines)


class TestFindOrders:
    def test__defaults(self) -> None:
        # Call
        filter_params = dtos.FindOrders()

        # Assert
        assert filter_params == dtos.FindOrders(customer_id=None, status=None, limit=20, offset=0)

    @pytest.mark.parametrize("limit", [0, dtos.MAX_PAGE_LIMIT + 1])
    def test__limit_out_of_range(self, limit: int) -> None:
        # Call and Assert
        with pytest.raises(ValueError, match="limit"):
            dtos.FindOrders(limit=limit)

    @pytest.mark.parametrize("offset", [-1, 2**31])
    def test__offset_out_of_range(self, offset: int) -> None:
        # Call and Assert
        with pytest.raises(ValueError, match="offset"):
            dtos.FindOrders(offset=offset)
