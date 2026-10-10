"""Composition root HTTP-сервиса: ``uvicorn orders_service.launchers.api:app``.

Граф зависимостей собирается в классах-неймспейсах при импорте модуля
(``Settings → Logger → Adapters → Application → Controllers``) — без DI-контейнера
и без FastAPI-``Depends``. Все адаптеры и сервисы — синглтоны процесса; ошибка конфигурации
проявляется на старте, а не на первом запросе.

Имена логгеров uvicorn живут здесь, а не в HTTP-адаптере: сервер выбирает launcher.
Уровень ``NOTSET`` означает «наследовать ``LOG_LEVEL``»; после импорта приложения наш
``dictConfig`` перехватывает эти логгеры в воркерах, две-три строки master-процесса
остаются в формате uvicorn.
"""

from functools import partial

from orders_service.adapters import api, database, log
from orders_service.application import entities, services
from orders_service.launchers import config

UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


class Settings:
    """Настройки процесса: адаптера БД, уровня приложения и логирования."""

    db = database.Settings()
    service = config.Settings()
    logging = log.Settings()


class Logger:
    """Логирование: уровень и формат из настроек; uvicorn и SQLAlchemy — в общий хендлер."""

    log.configure(
        Settings.logging,
        levels={**database.logger_levels(Settings.db), **dict.fromkeys(UVICORN_LOGGERS, "NOTSET")},
    )


class Adapters:
    """Исходящие адаптеры: движок БД и фабрика Unit of Work.

    ``uow_factory`` — вызываемый объект без аргументов: при каждом вызове сервис получает
    новый ``database.UnitOfWork`` над фабрикой сессий движка; это ``partial``, а не лямбда,
    потому что тело класса недоступно вложенным функциям, а присваивание лямбды запрещено
    линтером (E731).
    """

    db = database.Database(settings=Settings.db)
    uow_factory = partial(database.UnitOfWork, db.session_factory)


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
