from unittest.mock import Mock

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from orders_service.adapters import tracing
from orders_service.application import dtos, errors, interfaces


# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
@pytest.fixture(scope="function")
def order_service() -> Mock:
    return Mock(interfaces.Order)


@pytest.fixture(scope="function")
def traced_order(order_service: Mock) -> tracing.TracedOrder:
    return tracing.TracedOrder(order_service)


def _single(spans: InMemorySpanExporter) -> ReadableSpan:
    (span,) = spans.get_finished_spans()
    return span


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestTracedOrder:
    async def test__place_passes_arguments_and_result(
        self, traced_order: tracing.TracedOrder, order_service: Mock, spans: InMemorySpanExporter
    ) -> None:
        # Setup
        new_order_info = dtos.NewOrderInfo(
            customer_id=1, lines=[dtos.NewOrderLineInfo(product_id=7, quantity=2)]
        )
        order_service.place.return_value = Mock(dtos.Order)

        # Call
        result = await traced_order.place(new_order_info)

        # Assert
        order_service.place.assert_awaited_once_with(new_order_info)
        assert result is order_service.place.return_value
        span = _single(spans)
        assert span.name == "Order.place"
        assert span.status.status_code is StatusCode.UNSET

    async def test__find_returns_list(
        self, traced_order: tracing.TracedOrder, order_service: Mock, spans: InMemorySpanExporter
    ) -> None:
        # Setup
        filter_params = Mock(dtos.FindOrders)
        found = [Mock(dtos.Order), Mock(dtos.Order)]
        order_service.find.return_value = found

        # Call
        result = await traced_order.find(filter_params)

        # Assert
        order_service.find.assert_awaited_once_with(filter_params)
        assert result is found
        assert _single(spans).name == "Order.find"

    async def test__get(
        self, traced_order: tracing.TracedOrder, order_service: Mock, spans: InMemorySpanExporter
    ) -> None:
        # Call
        result = await traced_order.get(1)

        # Assert
        order_service.get.assert_awaited_once_with(1)
        assert result is order_service.get.return_value
        assert _single(spans).name == "Order.get"

    async def test__pay(
        self, traced_order: tracing.TracedOrder, order_service: Mock, spans: InMemorySpanExporter
    ) -> None:
        # Call
        result = await traced_order.pay(1)

        # Assert
        order_service.pay.assert_awaited_once_with(1)
        assert result is order_service.pay.return_value
        assert _single(spans).name == "Order.pay"

    async def test__cancel(
        self, traced_order: tracing.TracedOrder, order_service: Mock, spans: InMemorySpanExporter
    ) -> None:
        # Call
        result = await traced_order.cancel(1)

        # Assert
        order_service.cancel.assert_awaited_once_with(1)
        assert result is order_service.cancel.return_value
        assert _single(spans).name == "Order.cancel"

    async def test__domain_error_is_not_a_span_error(
        self, traced_order: tracing.TracedOrder, order_service: Mock, spans: InMemorySpanExporter
    ) -> None:
        # Setup
        order_service.get.side_effect = errors.OrderNotFound(id=1)

        # Call
        with pytest.raises(errors.OrderNotFound):
            await traced_order.get(1)

        # Assert
        span = _single(spans)
        assert span.status.status_code is StatusCode.UNSET
        assert span.attributes is not None
        assert span.attributes[tracing.ERROR_CODE_ATTRIBUTE] == "order_not_found"

    async def test__storage_unavailable_marks_span_with_cause(
        self, traced_order: tracing.TracedOrder, order_service: Mock, spans: InMemorySpanExporter
    ) -> None:
        # Setup
        failure = errors.StorageUnavailable()
        failure.__cause__ = ConnectionError("обрыв")
        order_service.pay.side_effect = failure

        # Call
        with pytest.raises(errors.StorageUnavailable):
            await traced_order.pay(1)

        # Assert
        span = _single(spans)
        assert span.status.status_code is StatusCode.ERROR
        (event,) = span.events
        assert event.attributes is not None
        assert event.attributes["exception.type"] == "ConnectionError"

    async def test__span_is_child_of_current(
        self, traced_order: tracing.TracedOrder, spans: InMemorySpanExporter
    ) -> None:
        # Call
        with tracing.span("request"):
            await traced_order.get(1)

        # Assert
        scenario, request = spans.get_finished_spans()
        request_context = request.get_span_context()
        assert scenario.parent is not None
        assert request_context is not None
        assert scenario.parent.span_id == request_context.span_id


class TestTracedCustomer:
    async def test__add(self, spans: InMemorySpanExporter) -> None:
        # Setup
        customer_service = Mock(interfaces.Customer)
        new_customer_info = dtos.NewCustomerInfo(name="Иван", email="ivan@example.com")

        # Call
        result = await tracing.TracedCustomer(customer_service).add(new_customer_info)

        # Assert
        customer_service.add.assert_awaited_once_with(new_customer_info)
        assert result is customer_service.add.return_value
        assert _single(spans).name == "Customer.add"


class TestTracedProduct:
    async def test__get(self, spans: InMemorySpanExporter) -> None:
        # Setup
        product_service = Mock(interfaces.Product)

        # Call
        result = await tracing.TracedProduct(product_service).get(7)

        # Assert
        product_service.get.assert_awaited_once_with(7)
        assert result is product_service.get.return_value
        assert _single(spans).name == "Product.get"
