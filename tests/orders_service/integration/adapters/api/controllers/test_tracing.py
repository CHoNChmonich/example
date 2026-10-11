import logging
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from orders_service.adapters import log, tracing
from orders_service.adapters.api import V1Controller, create_app
from orders_service.application import dtos, errors, interfaces

# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
CUSTOMER = dtos.Customer(id=1, name="Иван", email="ivan@example.com")
TRACE_ID = "0af7651916cd43dd8448eb211c80319c"


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestTelemetry:
    async def test__request_span_named_by_route(
        self, customer_service: Mock, client: httpx.AsyncClient, spans: InMemorySpanExporter
    ) -> None:
        # Setup
        customer_service.get.return_value = CUSTOMER

        # Call
        await client.get("/api/v1/customers/1")

        # Assert
        (span,) = spans.get_finished_spans()
        assert span.kind is SpanKind.SERVER
        assert span.attributes is not None
        assert span.attributes["http.route"] == "/api/v1/customers/{customer_id}"
        assert "/api/v1/customers/{customer_id}" in span.name

    async def test__healthcheck_excluded(
        self, client: httpx.AsyncClient, spans: InMemorySpanExporter
    ) -> None:
        # Call
        response = await client.get("/api/v1/healthcheck")

        # Assert
        assert response.status_code == 200
        assert spans.get_finished_spans() == ()

    async def test__traceparent_continued(
        self, customer_service: Mock, client: httpx.AsyncClient, spans: InMemorySpanExporter
    ) -> None:
        # Setup
        customer_service.get.return_value = CUSTOMER

        # Call
        await client.get(
            "/api/v1/customers/1",
            headers={"traceparent": f"00-{TRACE_ID}-b7ad6b7169203331-01"},
        )

        # Assert
        (span,) = spans.get_finished_spans()
        span_context = span.get_span_context()
        assert span_context is not None
        assert f"{span_context.trace_id:032x}" == TRACE_ID

    async def test__unhandled_error_marks_span(
        self, app: FastAPI, customer_service: Mock, spans: InMemorySpanExporter
    ) -> None:
        # Setup
        customer_service.get.side_effect = RuntimeError("boom")
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

        # Call
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/customers/1")

        # Assert
        assert response.status_code == 500
        (span,) = spans.get_finished_spans()
        assert span.status.status_code is StatusCode.ERROR

    async def test__routing_error_has_span(
        self, client: httpx.AsyncClient, spans: InMemorySpanExporter
    ) -> None:
        # Call
        response = await client.get("/api/v1/unknown")

        # Assert: 404 — обычный ответ, спан есть и не помечен ошибкой
        assert response.status_code == 404
        (span,) = spans.get_finished_spans()
        assert span.status.status_code is not StatusCode.ERROR

    async def test__healthcheck_excluded_under_root_path(
        self, app: FastAPI, spans: InMemorySpanExporter
    ) -> None:
        # Setup: приложение смонтировано под префиксом — path по ASGI включает root_path
        transport = httpx.ASGITransport(app=app, root_path="/orders")

        # Call
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/orders/api/v1/healthcheck")

        # Assert
        assert response.status_code == 200
        assert spans.get_finished_spans() == ()

    async def test__scenario_span_is_child_of_request_span(
        self, customer_service: Mock, product_service: Mock, spans: InMemorySpanExporter
    ) -> None:
        # Setup: контроллер на декораторе над портом — как собирает composition root
        order_service = Mock(interfaces.Order)
        order_service.get.side_effect = errors.OrderNotFound(id=1)
        controller = V1Controller(
            customer=customer_service,
            product=product_service,
            order=tracing.TracedOrder(order_service),
        )
        app = create_app(v1_controller=controller)

        # Call
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/orders/1")

        # Assert: спан сценария под серверным, ошибка ядра — код без ERROR, 404 без ERROR
        assert response.status_code == 404
        scenario, request = spans.get_finished_spans()
        request_context = request.get_span_context()
        assert scenario.name == "Order.get"
        assert scenario.parent is not None
        assert request_context is not None
        assert scenario.parent.span_id == request_context.span_id
        assert scenario.status.status_code is StatusCode.UNSET
        assert scenario.attributes is not None
        assert scenario.attributes[tracing.ERROR_CODE_ATTRIBUTE] == "order_not_found"
        assert request.kind is SpanKind.SERVER
        assert request.status.status_code is not StatusCode.ERROR

    async def test__log_record_carries_trace_id_of_request(
        self,
        customer_service: Mock,
        client: httpx.AsyncClient,
        spans: InMemorySpanExporter,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Setup: тот же фильтр, что на хендлере приложения, — на хендлере caplog
        customer_service.get.side_effect = errors.StorageUnavailable()
        caplog.handler.addFilter(log.LogContextFilter())
        handlers_logger = "orders_service.adapters.api.error_handlers"

        # Call: клиент передаёт traceparent — его trace_id и окажется в записи
        with caplog.at_level(logging.WARNING, logger=handlers_logger):
            await client.get(
                "/api/v1/customers/1",
                headers={"traceparent": f"00-{TRACE_ID}-b7ad6b7169203331-01"},
            )

        # Assert: запись обработчика связана с запросом trace_id его спана
        (span,) = spans.get_finished_spans()
        span_context = span.get_span_context()
        assert span_context is not None
        (record,) = [record for record in caplog.records if record.name == handlers_logger]
        assert record.__dict__["trace_id"] == TRACE_ID
        assert record.__dict__["trace_id"] == f"{span_context.trace_id:032x}"
