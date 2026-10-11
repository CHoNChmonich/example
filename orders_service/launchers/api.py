"""Composition root HTTP-сервиса: ``uvicorn orders_service.launchers.api:app``.

Граф зависимостей собирается в классах-неймспейсах при импорте модуля
(``Settings → Logger → Tracing → Adapters → Application → Decorators → Controllers``) — без
DI-контейнера и без FastAPI-``Depends``. Все адаптеры и сервисы — синглтоны процесса; ошибка
конфигурации проявляется на старте, а не на первом запросе. Трассировку сценариев и единиц
работы добавляют декораторы из ``adapters.tracing``: ядро, ``database.UnitOfWork`` и
``Database`` о спанах не знают, решение «что трассировать» принимается здесь.

Имена логгеров uvicorn живут здесь, а не в HTTP-адаптере: сервер выбирает launcher.
Уровень ``NOTSET`` означает «наследовать ``LOG_LEVEL``»; после импорта приложения наш
``dictConfig`` перехватывает эти логгеры в воркерах, две-три строки master-процесса
остаются в формате uvicorn.
"""

from functools import partial

from orders_service.adapters import api, database, log, tracing
from orders_service.application import entities, interfaces, services
from orders_service.launchers import config

UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


class Settings:
    """Настройки процесса: адаптера БД, уровня приложения, логирования и трассировки."""

    db = database.Settings()
    service = config.Settings()
    logging = log.Settings()
    trace = tracing.Settings()


class Logger:
    """Логирование: уровень и формат из настроек; uvicorn и SQLAlchemy — в общий хендлер."""

    log.configure(
        Settings.logging,
        levels={**database.logger_levels(Settings.db), **dict.fromkeys(UVICORN_LOGGERS, "NOTSET")},
    )


class Tracing:
    """Провайдер трассировки процесса; спаны создают адаптеры и декораторы, созданные ниже."""

    provider = tracing.configure(Settings.trace)


class Adapters:
    """Исходящие адаптеры: движок БД с трассируемым пулом, SQL-спаны и фабрика Unit of Work.

    Движок получает ``TracedPool`` (спан на взятие соединения) и слушатели SQL-спанов здесь:
    ``Database`` о трассировке не знает. ``uow_factory`` — вызываемый объект без аргументов
    (``interfaces.UnitOfWorkFactory``): на каждый вызов новый ``database.UnitOfWork`` под
    декоратором ``TracedUnitOfWork``; статический метод, а не ``partial``, потому что декоратор
    оборачивает экземпляр, который нужно создать в момент вызова.
    """

    db = database.Database(settings=Settings.db, poolclass=database.spans.TracedPool)
    database.spans.instrument(db.engine)

    @staticmethod
    def uow_factory() -> interfaces.UnitOfWork:
        """Создаёт единицу работы под спаном ``unit_of_work``.

        Returns:
            ``TracedUnitOfWork`` над новым ``database.UnitOfWork`` на фабрике сессий движка.
        """
        return tracing.TracedUnitOfWork(database.UnitOfWork(Adapters.db.session_factory))


class Application:
    """Сервисы ядра; выбор стратегии скидки — здесь, параметры — из настроек."""

    discount_policy = entities.VolumeDiscount(
        min_quantity=Settings.service.DISCOUNT_MIN_QUANTITY,
        percent=Settings.service.DISCOUNT_PERCENT,
    )
    customer = services.Customer(uow_factory=Adapters.uow_factory)
    product = services.Product(uow_factory=Adapters.uow_factory)
    order = services.Order(uow_factory=Adapters.uow_factory, discount_policy=discount_policy)


class Decorators:
    """Сценарии под спанами: Decorator над сервисами ядра; контроллер получает их, не сервисы."""

    customer = tracing.TracedCustomer(Application.customer)
    product = tracing.TracedProduct(Application.product)
    order = tracing.TracedOrder(Application.order)


class Controllers:
    """Входящие адаптеры: контроллер API v1 с внедрёнными портами сценариев."""

    v1_controller = api.V1Controller(
        customer=Decorators.customer,
        product=Decorators.product,
        order=Decorators.order,
    )


lifespan = api.create_lifespan(
    setup=[Adapters.db.aopen],
    cleanup=[Adapters.db.aclose, partial(tracing.shutdown, Tracing.provider)],
)
app = api.create_app(v1_controller=Controllers.v1_controller, lifespan=lifespan)
