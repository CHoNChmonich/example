"""Императивный маппинг сущностей ядра на таблицы.

Ядро не знает о SQLAlchemy: dataclass'ы ``entities`` инструментируются здесь при импорте.
``lazy="selectin"`` обязателен — ленивая загрузка в async-сессии недопустима.
"""

from sqlalchemy.orm import registry, relationship

from orders_service.application import entities

from . import tables

mapper = registry()

mapper.map_imperatively(entities.Customer, tables.customers)
mapper.map_imperatively(entities.Product, tables.products)
mapper.map_imperatively(
    entities.Order,
    tables.orders,
    properties={
        "lines": relationship(
            entities.OrderLine,
            lazy="selectin",
            cascade="all, delete-orphan",
            order_by=tables.order_lines.c.id,
        )
    },
)
mapper.map_imperatively(entities.OrderLine, tables.order_lines)
