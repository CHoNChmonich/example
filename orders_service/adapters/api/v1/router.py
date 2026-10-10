"""Маршруты v1 объявляются императивно — так маршрутизация остаётся вне контроллера.

Этот модуль и есть рукописный контракт API: пути, ``operation_id``, теги и карты ответов.
"""

from typing import Any

from fastapi import APIRouter

from orders_service.adapters.api.dtos import ErrorResponse
from orders_service.adapters.api.v1.controller import Controller


def create_router(controller: Controller, *, prefix: str = "/api/v1") -> APIRouter:
    """Объявляет маршруты v1 поверх методов контроллера.

    Args:
        controller: Контроллер, методы которого становятся обработчиками.
        prefix: Префикс путей маршрутизатора.

    Returns:
        Маршрутизатор с путями, ``operation_id``, тегами и картами ответов.
    """
    busy_response: dict[str, Any] = {
        "model": ErrorResponse,
        "description": "Хранилище временно недоступно; повторите запрос",
        "headers": {
            "Retry-After": {
                "description": "Через сколько секунд повторить запрос.",
                "schema": {"type": "integer", "minimum": 1},
            }
        },
    }
    default_responses: dict[int | str, dict[str, Any]] = {
        400: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        503: busy_response,
    }
    not_found_responses: dict[int | str, dict[str, Any]] = {
        **default_responses,
        404: {"model": ErrorResponse},
    }
    conflict_responses: dict[int | str, dict[str, Any]] = {
        **default_responses,
        409: {"model": ErrorResponse},
    }

    router = APIRouter(prefix=prefix)

    router.add_api_route(
        "/customers",
        controller.create_customer,
        methods=["POST"],
        tags=["v1: Customers"],
        summary="Зарегистрировать клиента",
        operation_id="createCustomer",
        status_code=201,
        responses=conflict_responses,
    )
    router.add_api_route(
        "/customers/{customer_id}",
        controller.get_customer,
        methods=["GET"],
        tags=["v1: Customers"],
        summary="Получить клиента по id",
        operation_id="getCustomerById",
        responses=not_found_responses,
    )
    router.add_api_route(
        "/products",
        controller.create_product,
        methods=["POST"],
        tags=["v1: Products"],
        summary="Добавить товар с начальным остатком",
        operation_id="createProduct",
        status_code=201,
        responses=default_responses,
    )
    router.add_api_route(
        "/products/{product_id}",
        controller.get_product,
        methods=["GET"],
        tags=["v1: Products"],
        summary="Получить товар по id",
        operation_id="getProductById",
        responses=not_found_responses,
    )
    router.add_api_route(
        "/orders",
        controller.place_order,
        methods=["POST"],
        tags=["v1: Orders"],
        summary="Оформить заказ: резерв остатков, скидка, сохранение — одной транзакцией",
        operation_id="placeOrder",
        status_code=201,
        responses=not_found_responses,
    )
    router.add_api_route(
        "/orders",
        controller.list_orders,
        methods=["GET"],
        tags=["v1: Orders"],
        summary="Найти заказы по клиенту и статусу",
        operation_id="listOrders",
        responses=default_responses,
    )
    router.add_api_route(
        "/orders/{order_id}",
        controller.get_order,
        methods=["GET"],
        tags=["v1: Orders"],
        summary="Получить заказ по id",
        operation_id="getOrderById",
        responses=not_found_responses,
    )
    router.add_api_route(
        "/orders/{order_id}/pay",
        controller.pay_order,
        methods=["POST"],
        tags=["v1: Orders"],
        summary="Оплатить заказ (new → paid)",
        operation_id="payOrder",
        responses=not_found_responses,
    )
    router.add_api_route(
        "/orders/{order_id}/cancel",
        controller.cancel_order,
        methods=["POST"],
        tags=["v1: Orders"],
        summary="Отменить заказ и вернуть остатки (new → cancelled)",
        operation_id="cancelOrder",
        responses=not_found_responses,
    )
    router.add_api_route(
        "/healthcheck",
        controller.healthcheck,
        methods=["GET"],
        include_in_schema=False,
    )
    return router
