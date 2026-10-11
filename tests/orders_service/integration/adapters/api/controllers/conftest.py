"""Тесты контроллеров: настоящее приложение FastAPI поверх моков портов сценариев."""

from collections.abc import AsyncIterator
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI

from orders_service.adapters.api import V1Controller, create_app
from orders_service.application import interfaces


@pytest.fixture(scope="function")
def customer_service() -> Mock:
    return Mock(interfaces.Customer)


@pytest.fixture(scope="function")
def product_service() -> Mock:
    return Mock(interfaces.Product)


@pytest.fixture(scope="function")
def order_service() -> Mock:
    return Mock(interfaces.Order)


@pytest.fixture(scope="function")
def app(customer_service: Mock, product_service: Mock, order_service: Mock) -> FastAPI:
    controller = V1Controller(
        customer=customer_service, product=product_service, order=order_service
    )
    return create_app(v1_controller=controller)


@pytest.fixture(scope="function")
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
