"""Схема БД: таблицы и ``metadata`` (единственный источник для Alembic и для маппинга)."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
)

from orders_service.application.entities import OrderStatus

naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=naming_convention)

customers = Table(
    "customers",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(255), nullable=False),
    Column("email", String(255), nullable=False, unique=True),
)

products = Table(
    "products",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(255), nullable=False),
    Column("price", Numeric(12, 2), nullable=False),
    Column("stock", Integer, nullable=False),
    CheckConstraint("stock >= 0", name="stock_non_negative"),
)

orders = Table(
    "orders",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "customer_id",
        Integer,
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    # В БД хранятся значения перечисления (new/paid/cancelled), а не имена членов;
    # CHECK-ограничение охраняет этот список на стороне БД.
    Column(
        "status",
        Enum(
            OrderStatus,
            name="order_status",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    ),
    # Скидка считается от суммы заказа: 100 строк × цена до 12 знаков × 10^6 единиц
    # (границы DTO) помещаются в 20 знаков.
    Column("discount", Numeric(20, 2), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

order_lines = Table(
    "order_lines",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "order_id",
        Integer,
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column(
        "product_id",
        Integer,
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("quantity", Integer, nullable=False),
    Column("unit_price", Numeric(12, 2), nullable=False),
    CheckConstraint("quantity > 0", name="quantity_positive"),
)
