from datetime import UTC, datetime
from decimal import Decimal
from itertools import cycle

from sqlalchemy import Table, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from orders_service.adapters.database import tables
from orders_service.application import entities

CUSTOMERS_DATA = [
    {"name": "Клиент 1", "email": "customer1@example.com"},
    {"name": "Клиент 2", "email": "customer2@example.com"},
    {"name": "Клиент 3", "email": "customer3@example.com"},
]

PRODUCTS_DATA = [
    {"name": "Товар 1", "price": Decimal("10.00"), "stock": 5},
    {"name": "Товар 2", "price": Decimal("2.50"), "stock": 10},
    {"name": "Товар 3", "price": Decimal("100.00"), "stock": 0},
]

ORDERS_DATA = [
    {
        "status": entities.OrderStatus.NEW,
        "discount": Decimal("0.00"),
        "created_at": datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
    },
    {
        "status": entities.OrderStatus.PAID,
        "discount": Decimal("1.00"),
        "created_at": datetime(2026, 10, 2, 12, 0, tzinfo=UTC),
    },
    {
        "status": entities.OrderStatus.NEW,
        "discount": Decimal("0.00"),
        "created_at": datetime(2026, 10, 3, 12, 0, tzinfo=UTC),
    },
    {
        "status": entities.OrderStatus.CANCELLED,
        "discount": Decimal("0.00"),
        "created_at": datetime(2026, 10, 4, 12, 0, tzinfo=UTC),
    },
]

ORDER_LINES_DATA = [
    {"quantity": 2, "unit_price": Decimal("10.00")},
    {"quantity": 8, "unit_price": Decimal("2.50")},
    {"quantity": 1, "unit_price": Decimal("100.00")},
    {"quantity": 3, "unit_price": Decimal("10.00")},
    {"quantity": 4, "unit_price": Decimal("2.50")},
]


async def insert_customers(session: AsyncSession) -> list[int]:
    """Вставляет данные в таблицу `customers`."""
    customers_insert = (
        insert(tables.customers).values(CUSTOMERS_DATA).returning(tables.customers.c.id)
    )
    return list((await session.execute(customers_insert)).scalars().all())


async def insert_products(session: AsyncSession) -> list[int]:
    """Вставляет данные в таблицу `products`."""
    products_insert = insert(tables.products).values(PRODUCTS_DATA).returning(tables.products.c.id)
    return list((await session.execute(products_insert)).scalars().all())


async def insert_orders(customer_ids: list[int], session: AsyncSession) -> list[int]:
    """Вставляет данные в таблицу `orders`: заказы раздаются клиентам по кругу."""
    updated_orders_data = [
        {**order, "customer_id": customer_id}
        for order, customer_id in zip(ORDERS_DATA, cycle(customer_ids), strict=False)
    ]
    orders_insert = insert(tables.orders).values(updated_orders_data).returning(tables.orders.c.id)
    return list((await session.execute(orders_insert)).scalars().all())


async def insert_order_lines(
    order_ids: list[int], product_ids: list[int], session: AsyncSession
) -> list[int]:
    """Вставляет данные в таблицу `order_lines`: строки раздаются заказам и товарам по кругу."""
    updated_lines_data = [
        {**line, "order_id": order_id, "product_id": product_id}
        for line, order_id, product_id in zip(
            ORDER_LINES_DATA, cycle(order_ids), cycle(product_ids), strict=False
        )
    ]
    lines_insert = (
        insert(tables.order_lines).values(updated_lines_data).returning(tables.order_lines.c.id)
    )
    return list((await session.execute(lines_insert)).scalars().all())


async def count_rows(table: Table, session: AsyncSession) -> int:
    """Количество строк в таблице."""
    count = (await session.execute(select(func.count()).select_from(table))).scalar_one()
    return int(count)


async def select_stock(product_id: int, session: AsyncSession) -> int:
    """Остаток товара из БД (Core-запрос, минуя identity map сессии)."""
    query = select(tables.products.c.stock).where(tables.products.c.id == product_id)
    return int((await session.execute(query)).scalar_one())
