"""Composition root HTTP-сервиса: ``uvicorn orders_service.launchers.api:app``.

Граф зависимостей собирается в классах-неймспейсах при импорте модуля
(``Settings → Logger → Adapters → Application → Controllers``) — без DI-контейнера
и без FastAPI-``Depends``. Все адаптеры и сервисы — синглтоны процесса; ошибка конфигурации
проявляется на старте, а не на первом запросе.
"""

import logging

from orders_service.adapters import api, database
from orders_service.application import entities, services
from orders_service.launchers import config


class Settings:
    """Настройки процесса: адаптера БД и уровня приложения."""

    db = database.Settings()
    service = config.Settings()


class Logger:
    """Корневой логгер приложения; uvicorn настраивает только свои логгеры."""

    logging.basicConfig(level=Settings.service.LOG_LEVEL.upper())


class Adapters:
    """Исходящие адаптеры: движок БД и фабрика Unit of Work."""

    db = database.Database(settings=Settings.db)
    uow_factory = database.UnitOfWorkFactory(session_factory=db.session_factory)


class Application:
    """Сервисы ядра; выбор стратегии скидки — здесь, параметры — из настроек."""

    discount_policy = entities.VolumeDiscount(
        min_quantity=Settings.service.DISCOUNT_MIN_QUANTITY,
        percent=Settings.service.DISCOUNT_PERCENT,
    )
    customer = services.Customer(uow_factory=Adapters.uow_factory)
    product = services.Product(uow_factory=Adapters.uow_factory)
    order = services.Order(uow_factory=Adapters.uow_factory, discount_policy=discount_policy)


class Controllers:
    """Входящие адаптеры: контроллер API v1 с внедрёнными сервисами."""

    v1_controller = api.V1Controller(
        customer=Application.customer,
        product=Application.product,
        order=Application.order,
    )


lifespan = api.create_lifespan(setup=[Adapters.db.aopen], cleanup=[Adapters.db.aclose])
app = api.create_app(v1_controller=Controllers.v1_controller, lifespan=lifespan)
