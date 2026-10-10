from datetime import UTC, datetime
from decimal import Decimal

import pytest

from orders_service.application import entities, errors


# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
def _order(*quantities: int, unit_price: str = "10.00") -> entities.Order:
    lines = [
        entities.OrderLine(product_id=index, quantity=quantity, unit_price=Decimal(unit_price))
        for index, quantity in enumerate(quantities, start=1)
    ]
    return entities.Order(id=1, customer_id=1, lines=lines)


@pytest.fixture(scope="function")
def product() -> entities.Product:
    return entities.Product(id=1, name="Кружка", price=Decimal("10.00"), stock=5)


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestProduct:
    def test__reserve(self, product: entities.Product) -> None:
        # Call
        product.reserve(3)

        # Assert
        assert product.stock == 2

    def test__insufficient_stock(self, product: entities.Product) -> None:
        # Call and Assert
        with pytest.raises(errors.InsufficientStock) as exc_info:
            product.reserve(6)

        assert exc_info.value.context == {"product_id": 1, "requested": 6, "available": 5}
        assert product.stock == 5

    def test__release(self, product: entities.Product) -> None:
        # Call
        product.release(3)

        # Assert
        assert product.stock == 8


class TestOrderLine:
    def test__total(self) -> None:
        # Setup
        line = entities.OrderLine(product_id=1, quantity=3, unit_price=Decimal("2.50"))

        # Assert
        assert line.total == Decimal("7.50")


class TestOrder:
    def test__totals_without_discount(self) -> None:
        # Setup
        order = _order(2, 3)

        # Assert
        assert order.total_quantity == 5
        assert order.subtotal == Decimal("50.00")
        assert order.discount == Decimal("0")
        assert order.total == Decimal("50.00")

    def test__created_at_does_not_affect_equality(self) -> None:
        # Setup
        first = _order(1)
        second = _order(1)
        second.created_at = datetime(2000, 1, 1, tzinfo=UTC)

        # Assert
        assert first == second
        assert first.created_at != second.created_at


class TestDiscountPolicies:
    def test__no_discount(self) -> None:
        # Setup
        order = _order(10)

        # Call
        order.apply_discount(entities.NoDiscount())

        # Assert
        assert order.discount == Decimal("0")
        assert order.total == Decimal("100.00")

    def test__volume_discount_at_threshold(self) -> None:
        # Setup
        order = _order(4, 6)  # 10 единиц, порог включительно
        policy = entities.VolumeDiscount(min_quantity=10, percent=Decimal("5"))

        # Call
        order.apply_discount(policy)

        # Assert
        assert order.discount == Decimal("5.00")
        assert order.total == Decimal("95.00")

    def test__volume_discount_below_threshold(self) -> None:
        # Setup
        order = _order(9)
        policy = entities.VolumeDiscount(min_quantity=10, percent=Decimal("5"))

        # Call
        order.apply_discount(policy)

        # Assert
        assert order.discount == Decimal("0")

    def test__volume_discount_rounds_half_up(self) -> None:
        # Setup
        order = _order(3, unit_price="3.33")  # 9.99 × 7 % = 0.6993 → 0.70
        policy = entities.VolumeDiscount(min_quantity=1, percent=Decimal("7"))

        # Call
        order.apply_discount(policy)

        # Assert
        assert order.discount == Decimal("0.70")


class TestOrderStates:
    def test__pay(self) -> None:
        # Setup
        order = _order(1)

        # Call
        order.pay()

        # Assert
        assert order.status is entities.OrderStatus.PAID

    def test__cancel(self) -> None:
        # Setup
        order = _order(1)

        # Call
        order.cancel()

        # Assert
        assert order.status is entities.OrderStatus.CANCELLED

    @pytest.mark.parametrize(
        "status, action",
        [
            (entities.OrderStatus.PAID, "pay"),
            (entities.OrderStatus.PAID, "cancel"),
            (entities.OrderStatus.CANCELLED, "pay"),
            (entities.OrderStatus.CANCELLED, "cancel"),
        ],
    )
    def test__transition_not_allowed(self, status: entities.OrderStatus, action: str) -> None:
        # Setup
        order = _order(1)
        order.status = status

        # Call and Assert
        with pytest.raises(errors.OrderTransitionNotAllowed) as exc_info:
            getattr(order, action)()

        assert exc_info.value.context == {"id": 1, "status": status, "action": action}
        assert order.status is status
