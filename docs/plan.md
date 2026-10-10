# План реализации: учебный сервис «Заказы» (гексагональная архитектура + Unit of Work)

Статус: **v3 — утверждён к реализации** (кросс-ревью v1 — раздел 14; решения пользователя
от 2026-10-09 — раздел 13). После реализации этот файл остаётся как история проектирования;
действующие правила переносятся в README.

---

## 1. Цель и рамки

**Что делаем.** Небольшой HTTP-сервис заказов: клиенты, товары, заказы. Python 3.12,
FastAPI, SQLAlchemy 2 (async, asyncpg), PostgreSQL 17, Alembic, Pydantic v2, uv,
docker compose. Назначение — наглядный пример гексагональной архитектуры (Ports & Adapters)
с явным применением SOLID и паттернов GoF, с паттерном **Unit of Work**, объединяющим
несколько репозиториев.

**Образцы (зафиксировано пользователем, не обсуждается):**

1. Слои и правила слоёв — как в `../hex_arch/` (`application → adapters → launchers`,
   ядро не знает ни SQLAlchemy, ни FastAPI; сущности — dataclass'ы с императивным
   маппингом в адаптере; `interfaces/` — ABC только для исходящих портов; входящих портов нет,
   контроллер зависит от конкретных `services.X`; DTO/сущности между слоями, не dict/list;
   launcher — composition root в классах-неймспейсах; одинаковые имена в разных модулях
   различаются модулем импорта: `interfaces.OrdersRepo` / `database.repositories.OrdersRepo`).
2. API-ручки и их инициализация — как в `../interactive_panels/components/backend/`
   (`adapters/api`: `create_app()`, `create_lifespan()`, `register_error_handlers()`,
   класс `Controller` с инжектированными сервисами, `create_router()` с императивным
   `router.add_api_route(...)`, `operation_id`/`tags`/`summary`/`responses`; API-уровневые
   `schemas/*Body.to_application()` и `dtos/*Response.from_application()` — отдельный шов,
   модели ядра наружу не торчат; composition root `launchers/api.py` в классах-неймспейсах
   `Settings → Adapters → Application → Controllers`).
3. **UoW объединяет несколько репозиториев и прокидывается в сервисные классы методом-обёрткой:
   объект UoW и объекты репозиториев создаются прямо в сервисе при вызове метода.**
4. **Главное условие: обработчики FastAPI определяются в API-адаптере** как методы класса
   `Controller` и получают сервисы через конструктор — тем же «чистым» DI, что и все остальные
   сервисы и адаптеры. FastAPI-DI (`Depends()`) не используется нигде. `Path()/Query()/Body()` —
   это разбор запроса, а не внедрение зависимостей, они допустимы.

**Вне скоупа:** аутентификация, RabbitMQ/воркеры, nginx, pgAdmin, CI, фронтенд, prod-hardening
(gunicorn, TLS), i18n, сложные отчёты. Это учебный минимум.

---

## 2. Предметная область (минимум)

| Сущность | Поля | Правила |
|---|---|---|
| `Customer` | `id`, `name`, `email` | `email` уникален |
| `Product` | `id`, `name`, `price: Decimal`, `stock: int` | `reserve(qty)` уменьшает остаток, при нехватке — `InsufficientStock`; `release(qty)` возвращает |
| `Order` | `id`, `customer_id`, `status`, `discount: Decimal`, `created_at`, `lines: list[OrderLine]` | `subtotal` = Σ строк, `total = subtotal − discount`; `apply_discount(policy)` — точка применения Strategy; `pay()/cancel()` — через State |
| `OrderLine` | `id`, `order_id`, `product_id`, `quantity`, `unit_price` | `unit_price` фиксируется в момент заказа; `total = quantity × unit_price` |
| `OrderStatus` | `new`, `paid`, `cancelled` | `new → paid`, `new → cancelled`; `paid` и `cancelled` — конечные |

**Сценарии (use cases):**

- Клиенты: добавить, получить по id.
- Товары: добавить, получить по id.
- Заказы: оформить (проверить клиента и товары, зарезервировать остатки, применить скидку,
  сохранить заказ со строками — **одна транзакция через три репозитория**), получить по id,
  найти по фильтру, оплатить (`new → paid`), отменить (`new → cancelled` + вернуть остатки —
  **одна транзакция через два репозитория**).

Скидка — Strategy `DiscountPolicy`: `NoDiscount` и `VolumeDiscount(min_quantity, percent)`
(процент от суммы при общем количестве единиц ≥ порога, порог включительно, округление
`quantize(Decimal("0.01"), ROUND_HALF_UP)`). Политика и её параметры выбираются в launcher'е
из настроек (`DISCOUNT_MIN_QUANTITY`, `DISCOUNT_PERCENT`).

Одна строка заказа — один товар: дубли `product_id` в `lines` отклоняются валидацией DTO
(`NewOrderInfo`), а не «сливаются» молча.

---

## 3. Структура проекта

Плоская раскладка (один компонент — monorepo-обёртка `components/backend` не нужна).
`docker-compose.yml` и `.env` — в корне, чтобы стенд поднимался одной командой
`docker compose up -d --build` (compose читает `.env` рядом с собой; `deployment/` — только
Dockerfile и init-скрипт БД).

```
example/
├── .env.example                 # POSTGRES_*, APP_PORT, LOG_LEVEL, DISCOUNT_*, TEST_DATABASE_URL
├── .python-version              # 3.12
├── .editorconfig                # end_of_line = lf (Windows: иначе init-скрипт и shebang ломаются)
├── .gitattributes               # * text=auto eol=lf
├── .gitignore  .dockerignore
├── pyproject.toml  uv.lock
├── docker-compose.yml           # postgres (healthcheck) → migrate (one-shot) → api
├── README.md                    # запуск; слои; транзакции; словарь имён; SOLID/паттерны; диаграммы
├── docs/plan.md                 # этот план (история проектирования)
├── deployment/
│   ├── Dockerfile               # python:3.12-slim + uv, multi-stage, non-root (как interactive_panels)
│   └── postgres/init-test-db.sql# CREATE DATABASE orders_test; (docker-entrypoint-initdb.d, без шелла)
├── orders_service/
│   ├── __init__.py
│   ├── application/             # ЯДРО: не импортирует SQLAlchemy/FastAPI
│   │   ├── __init__.py
│   │   ├── entities.py          # домен: OrderStatus, DiscountPolicy (Strategy), состояния заказа
│   │   │                        #        (State), Customer, Product, Order, OrderLine
│   │   ├── errors.py            # Error → категории (NotFoundError, ConflictError,
│   │   │                        #        RuleViolationError, StorageUnavailable) → конкретные
│   │   ├── transactional.py     # метод-обёртка @transactional (концепция слоя, не «util»)
│   │   ├── interfaces/          # исходящие порты (ABC): customers.py, products.py, orders.py,
│   │   │                        #        unit_of_work.py (UnitOfWork, UnitOfWorkFactory)
│   │   ├── dtos/                # Pydantic: customer.py, product.py, order.py
│   │   │                        #        (NewXInfo — вход, X — выход, FindOrders — параметры поиска)
│   │   └── services/            # сервис на сущность: customer.py, product.py, order.py
│   ├── adapters/
│   │   ├── api/                 # FastAPI (внутри — по образцу interactive_panels)
│   │   │   ├── __init__.py      # create_app, create_lifespan, V1Controller
│   │   │   ├── app.py           # create_app(*, v1_controller, v1_prefix="/api/v1", lifespan=None)
│   │   │   ├── lifespan.py      # create_lifespan(*, setup, cleanup)
│   │   │   ├── error_handlers.py# register_error_handlers(app): категории ошибок → HTTP
│   │   │   ├── dtos.py          # ErrorResponse {error, code, context}
│   │   │   └── v1/
│   │   │       ├── __init__.py  # Controller, create_router
│   │   │       ├── controller.py# Controller(customer, product, order) — plain async-методы
│   │   │       ├── router.py    # create_router(controller, *, prefix) — add_api_route(...)
│   │   │       ├── schemas/     # customer.py, product.py, order.py — *Body.to_application()
│   │   │       └── dtos/        # customer.py, product.py, order.py — *Response.from_application()
│   │   └── database/            # SQLAlchemy (по образцу hex_arch/adapters/database)
│   │       ├── __init__.py      # импортирует mapping (регистрация маппинга!), экспортирует
│   │       │                    #   Settings, Database, UnitOfWorkFactory, metadata, repositories
│   │       ├── settings.py      # POSTGRES_* (pydantic-settings, env_file по пути от файла)
│   │       ├── database.py      # Database: async engine, session_factory, aopen/aclose
│   │       ├── tables.py        # Table(...) + metadata (naming_convention)
│   │       ├── mapping.py       # map_imperatively(entities.X, tables.x)
│   │       ├── repositories/    # base.py, customers.py, products.py, orders.py
│   │       ├── unit_of_work.py  # UnitOfWork, UnitOfWorkFactory (реализации портов)
│   │       ├── alembic/         # env.py (async), script.py.mako
│   │       └── migrations/      # 0001_initial (autogenerate + ручная правка)
│   └── launchers/
│       ├── __init__.py
│       ├── config.py            # Settings: LOG_LEVEL, DISCOUNT_MIN_QUANTITY, DISCOUNT_PERCENT
│       ├── api.py               # Settings → Adapters → Application → Controllers; lifespan; app
│       └── alembic_runner.py    # конфиг Alembic из настроек БД + констант (как hex_arch), без alembic.ini
└── tests/
    ├── unit/application/        # conftest.py (фикстуры uow/uow_factory/репозитории-моки),
    │                            #   test_entities.py, test_transactional.py, test_<service>.py
    ├── integration/api/         # conftest.py (client), test_<resource>.py — httpx + Mock(services.X)
    └── integration/database/    # conftest.py (TestSettings, engine, truncate), test_unit_of_work.py,
                                 #   test_repositories.py — реальный Postgres
```

Правила имён файлов: предметные модули — в единственном числе (`dtos/order.py`,
`services/order.py`, `v1/schemas/order.py`), репозитории и их порты — во множественном
(`interfaces/orders.py`, `repositories/orders.py`) — ровно как hex_arch (`dtos/patient.py` /
`interfaces/patients.py`). У каждого пакета — `__init__.py` с `__all__` (образец
`api/__init__.py`, `postgresql/__init__.py`). `py.typed` не нужен (приложение, не библиотека).

Соответствие образцам: трёхслойка, правила слоёв и плоская раскладка адаптеров
(`adapters/api`, `adapters/database`) — hex_arch; внутреннее устройство `adapters/api`
(`create_app`/`Controller`/`create_router`) — interactive_panels. Стартовый `main.py`
(шаблон PyCharm) удаляется.

---

## 4. Ключевые решения

### 4.1. Unit of Work + метод-обёртка `@transactional` (ядро требования)

**Порты (`application/interfaces/unit_of_work.py`):**

```python
class UnitOfWork(ABC):
    """Одна транзакция над несколькими репозиториями.

    Репозитории разделяют одну сессию и живут ровно одну транзакцию. Сервисы НЕ вызывают
    ``commit()`` сами — это делает обёртка ``@transactional`` при нормальном выходе из метода.
    ``__aexit__`` реализации обязан откатить всё незакоммиченное, закрыть сессию и перевести
    инфраструктурные ошибки хранилища в ``errors.StorageUnavailable``.
    """

    @property
    @abstractmethod
    def customers(self) -> CustomersRepo: ...  # абстрактные property, а не аннотации:
    @property  # иначе Mock(spec=UnitOfWork) не видит атрибутов
    @abstractmethod
    def products(self) -> ProductsRepo: ...
    @property
    @abstractmethod
    def orders(self) -> OrdersRepo: ...

    @abstractmethod
    async def __aenter__(self) -> Self: ...

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    @abstractmethod
    async def commit(self) -> None: ...


class UnitOfWorkFactory(ABC):
    """Паттерн: Abstract Factory (GoF).

    Создаёт согласованное семейство объектов одной транзакции: сессию, три репозитория
    на ней и UoW над ними. Подмена реализации (SQLAlchemy ↔ фейк в тестах) подменяет
    всё семейство разом.
    """

    @abstractmethod
    def create(self) -> UnitOfWork: ...
```

`rollback()` в порте нет: его вызывает только `__aexit__` реализации, ни один клиент ядра
им не пользуется (ISP). Почему фабрика, а не один объект UoW на сервис (как в книге cosmic
python): сервисы — синглтоны composition root'а, запросы в FastAPI конкурентны; UoW, хранящий
сессию в `self`, нельзя разделять между вызовами. Фабрика создаёт **новый UoW с новыми
репозиториями на каждый вызов** — это и есть «создавать объект UoW и объекты репозиториев
прямо в сервисе при вызове».

**Метод-обёртка (`application/transactional.py`, PEP 695, проверено `mypy --strict`):**

```python
class TransactionalService(Protocol):
    """Что обёртка требует от сервиса: фабрика UoW в публичном атрибуте."""

    uow_factory: interfaces.UnitOfWorkFactory


def transactional[S: TransactionalService, **P, R](
    method: Callable[Concatenate[S, interfaces.UnitOfWork, P], Awaitable[R]],
) -> Callable[Concatenate[S, P], Awaitable[R]]:
    """Граница транзакции = публичный метод сервиса.

    При вызове: создать UoW через ``self.uow_factory`` (внутри — сессия и репозитории),
    передать его методу первым аргументом после ``self``, ``commit`` при нормальном выходе;
    при исключении commit не выполняется, откат делает ``__aexit__`` UoW, исключение уходит
    наружу. Снаружи метод вызывается без ``uow``.
    """

    @wraps(method)
    async def wrapper(self: S, /, *args: P.args, **kwargs: P.kwargs) -> R:
        async with self.uow_factory.create() as uow:
            result = await method(self, uow, *args, **kwargs)
            await uow.commit()
            return result

    return wrapper
```

- `uow` — **первый позиционный параметр после `self`**: только так PEP 612 `Concatenate`
  даёт точную типизацию. `self` в обёртке — позиционно-только (`/`): без этого typeshed-тип
  `functools.wraps` (`_Wrapped` с именованным `self`) не сходится с `Callable[Concatenate[S, P], …]`
  (проверено: раздел 14). Что даёт mypy (проверено): вызов без `uow` типизирован точно
  (`reveal_type(order.place)` = `def (new_order_info: NewOrderInfo) -> Awaitable[Order]`),
  лишний аргумент → `call-arg`, неверный тип → `arg-type`, класс без `uow_factory` отвергается
  прямо на декораторе — это и есть довод в пользу `Protocol`.
- Commit делает обёртка, не метод: сервис описывает сценарий, транзакцией управляет аспект —
  то же разделение, что `TransactionContext` в hex_arch. Обёртка не ловит исключения и не
  вызывает rollback — это контракт `__aexit__`.
- **Вложенности нет** (в hex_arch — счётчик вложенности): публичный транзакционный метод —
  граница; общая для нескольких сценариев логика выносится в приватные хелперы,
  принимающие `uow` (как хелперы `strip_dead_targets_from_elements(transaction, …)`
  в interactive_panels). Вызов одного транзакционного метода из другого = две транзакции —
  в примере таких вызовов нет, правило фиксируется в README.
- Чтения (`get`, `find`) тоже идут через `@transactional`: репозитории существуют только
  внутри UoW; commit пустой транзакции в Postgres — холостой. Отдельный «read-only» режим
  не делаем (YAGNI).
- `functools.wraps` оставляет `__wrapped__`, поэтому `inspect.signature` покажет `uow`.
  Правило для тестов: `Mock(services.X)` (как в hex_arch), не `create_autospec`.

**Реализация (`adapters/database/unit_of_work.py`):**

```python
class UnitOfWork(interfaces.UnitOfWork):
    """Транзакция SQLAlchemy: три репозитория на одной AsyncSession."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        customers: repositories.CustomersRepo,
        products: repositories.ProductsRepo,
        orders: repositories.OrdersRepo,
    ) -> None:
        self._session = session  # все атрибуты заданы в __init__ — без Optional-проверок
        self._customers = customers
        self._products = products
        self._orders = orders

    @property
    def customers(self) -> interfaces.CustomersRepo:
        return self._customers

    # products / orders — так же

    async def __aenter__(self) -> Self:
        return self  # соединение берётся из пула при первом запросе (autobegin)

    async def __aexit__(self, exc_type, exc, tb) -> None:  # аннотации как в порте
        try:
            await self._session.rollback()  # после commit — холостой
        finally:
            await self._session.close()
        if _is_transient(exc):  # OperationalError | OSError | DBAPIError с sqlstate 40001/40P01
            raise errors.StorageUnavailable() from exc  # единственное место перевода ошибок СУБД

    async def commit(self) -> None:
        await self._session.commit()  # ошибка commit тоже попадёт в __aexit__ и будет переведена


class UnitOfWorkFactory(interfaces.UnitOfWorkFactory):
    """Паттерн: Abstract Factory (GoF) — семейство «сессия + репозитории + UoW»."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None: ...

    def create(self) -> UnitOfWork:
        session = self._session_factory()
        return UnitOfWork(
            session,
            customers=repositories.CustomersRepo(session),
            products=repositories.ProductsRepo(session),
            orders=repositories.OrdersRepo(session),
        )
```

Исключение, поднятое в `__aexit__`, заменяет исходное (с `from exc`) — так
`OperationalError` превращается в `errors.StorageUnavailable` → 503 с `Retry-After`,
а `IntegrityError` по UNIQUE(email) переводится раньше, в репозитории (раздел 4.2),
и `__aexit__` проходит сквозь него без изменений. Прочие `SQLAlchemyError` (ошибки
программиста) остаются как есть → общий обработчик 500 с логом.

Имена совпадают с именами портов и различаются модулем импорта (`interfaces.UnitOfWork`
vs `database.UnitOfWork`) — правило именования hex_arch.

**Сервис (эскиз, `application/services/order.py`):**

```python
class Order:
    """Сценарии заказа. Все публичные методы — границы транзакций (@transactional)."""

    def __init__(
        self, uow_factory: interfaces.UnitOfWorkFactory, discount_policy: entities.DiscountPolicy
    ) -> None:
        self.uow_factory = uow_factory
        self.discount_policy = discount_policy

    @transactional
    async def place(
        self, uow: interfaces.UnitOfWork, new_order_info: dtos.NewOrderInfo
    ) -> dtos.Order:
        """Оформить заказ. Поднимает CustomerNotFound, ProductNotFound, InsufficientStock."""
        if await uow.customers.fetch_by_id(new_order_info.customer_id) is None:
            raise errors.CustomerNotFound(id=new_order_info.customer_id)
        requested = {line.product_id: line.quantity for line in new_order_info.lines}
        products = await uow.products.fetch_by_ids(list(requested), for_update=True)
        missing = set(requested) - {product.id for product in products}
        if missing:
            raise errors.ProductNotFound(id=min(missing))
        lines = []
        for product in products:
            product.reserve(requested[product.id])  # InsufficientStock
            lines.append(
                entities.OrderLine(
                    product_id=product.id, quantity=requested[product.id], unit_price=product.price
                )
            )
        order = entities.Order(customer_id=new_order_info.customer_id, lines=lines)
        order.apply_discount(self.discount_policy)  # Паттерн: Strategy
        added = await uow.orders.add(order)
        return dtos.Order.model_validate(added)

    @transactional
    async def cancel(self, uow: interfaces.UnitOfWork, order_id: int) -> dtos.Order:
        """Отменить заказ и вернуть остатки. OrderNotFound, OrderTransitionNotAllowed."""
        order = await uow.orders.fetch_by_id(order_id, for_update=True)
        if order is None:
            raise errors.OrderNotFound(id=order_id)
        order.cancel()  # Паттерн: State
        by_product = {line.product_id: line.quantity for line in order.lines}
        for product in await uow.products.fetch_by_ids(list(by_product), for_update=True):
            product.release(by_product[product.id])
        return dtos.Order.model_validate(order)
```

Глаголы не дублируются между слоями: у сервиса `place`, у сущности — обычный конструктор
и `apply_discount` (точка применения Strategy видна в сервисе).

### 4.2. Домен и персистентность — как в hex_arch, но async

- `entities.py` — один модуль-домен (правило hex_arch «весь домен в `entities.py`»), с модульным
  докстрингом «Domain слой: перечисления, политики скидок (Strategy), состояния заказа (State),
  сущности» и секциями в этом порядке. `@dataclass(kw_only=True)` сущности с
  `id: int | None = None`; поведение там, где оно принадлежит сущности (`Product.reserve/release`,
  `Order.apply_discount/pay/cancel/subtotal/total/total_quantity`). Сущности поднимают ошибки из
  `application/errors.py` (тот же слой). `inspect`-магию hex_arch (`_ENTITIES`, `Entity = Union[...]`)
  не копировать.
- `Order.created_at: datetime = field(default_factory=lambda: datetime.now(UTC), compare=False)` —
  `compare=False`, чтобы `__eq__` dataclass'а (и `call.add(entities.Order(...))` в тестах)
  не зависел от времени.
- State (решение принято, раздел 13): абстрактный `_OrderState` с `pay(order)`/`cancel(order)`;
  `_NewOrderState` выполняет переходы, `_FinalOrderState` (для `paid` и `cancelled` — они ведут
  себя одинаково) поднимает `OrderTransitionNotAllowed`; `_STATES: dict[OrderStatus, _OrderState]`,
  `Order.pay()` = `_STATES[self.status].pay(self)`. Без пустых классов и магических строк;
  новый статус = новый класс состояния + строка в `_STATES`.
- Императивный маппинг (`mapping.py`): `registry().map_imperatively(...)`; `Order.lines` —
  `relationship(OrderLine, lazy="selectin", cascade="all, delete-orphan")` — **в async
  ленивая загрузка `lazy="select"` недопустима** (MissingGreenlet), поэтому `selectin`.
  **Регистрация маппинга — побочный эффект импорта `mapping.py`**: его импортирует
  `adapters/database/__init__.py` (как hex_arch `adapters/database/__init__.py`), поэтому
  любой импорт пакета адаптера (launcher, conftest интеграционных тестов) инструментирует
  сущности; `alembic/env.py` импортирует только `tables.metadata`.
- `async_sessionmaker(expire_on_commit=False)`; репозитории делают `flush()` после `add`,
  чтобы получить `id`; DTO собирается внутри транзакции (до commit). Цепочка проверена
  (раздел 14): `flush` выдаёт id, `selectin` подгружает строки, `model_validate(from_attributes=True)`
  читает `@property` и вложенный список, после commit атрибуты доступны.
- Статус — `StrEnum` в колонке `Enum(OrderStatus, native_enum=False, length=16)`; деньги —
  `Numeric(12, 2)` ↔ `Decimal`; `created_at` — `timestamptz`.
- Блокировки: `ProductsRepo.fetch_by_ids(ids, *, for_update=False)` строит
  `select(Product).where(Product.id.in_(ids)).order_by(Product.id).with_for_update()` —
  **порядок захвата задаёт `ORDER BY` в самом запросе** (Postgres ставит `LockRows` над `Sort`),
  сортировка списка в Python порядок блокировок не гарантирует. `OrdersRepo.fetch_by_id(id,
  *, for_update=False)` для `pay`/`cancel` — два параллельных `cancel` не вернут остаток дважды.
  `cancel` берёт заказ, потом товары; `place` — только товары, строку заказа не блокирует —
  цикла нет. Тест на перекрёстный порядок товаров — раздел 10.
- `OrdersRepo.fetch_all(FindOrders)` — динамический `WHERE` + обязательный `ORDER BY id`
  (детерминированная пагинация).
- Уникальность `email`: сервис делает предварительную проверку `fetch_by_email` (понятная
  ошибка на счастливом пути), гонку закрывает UNIQUE-констрейнт: `CustomersRepo.add()`
  переводит `IntegrityError` по этому констрейнту в `errors.CustomerAlreadyExists` (адаптер
  транслирует инфраструктурную ошибку в ошибку приложения — как в interactive_panels).

### 4.3. Модели данных — два шва

- `application/dtos` — Pydantic v2: `NewCustomerInfo` / `Customer`, `NewProductInfo` / `Product`,
  `NewOrderInfo{customer_id, lines: list[NewOrderLineInfo]}` (валидатор: `lines` непустой,
  `product_id` без дублей, `quantity ≥ 1`) / `OrderLine`, `Order`, а также `FindOrders(customer_id?,
  status?, limit=20 (1..200), offset=0)`. Все выходные DTO — `from_attributes=True` (включая
  вложенный `OrderLine`). Пакет `application/schemas` hex_arch **не заводим**: в нём был бы один
  класс, а слово `schemas` уже занято API-швом с другим смыслом (тела запросов) — `FindOrders`
  живёт в `dtos/order.py`; hex_arch сам называет schemas «специализированной формой DTO».
  Валидация входа происходит при построении DTO на границе; `validate_call` на методах
  сервисов не используем (решение пользователя, раздел 13).
- `adapters/api/v1/schemas` (`CustomerCreateBody`, `ProductCreateBody`,
  `OrderCreateBody{customer_id, lines: list[OrderLineCreateBody]}`, перечисление
  `api_schemas.OrderStatus` для `?status=` → `to_application()`) и `v1/dtos`
  (`CustomerResponse`, `ProductResponse`, `OrderResponse{status: api_schemas.OrderStatus,
  lines: list[OrderLineResponse]}`, `OrderListResponse{items}` ← `from_application()`),
  `extra="forbid"`, `examples=` для Swagger — как в interactive_panels. Перечисление статуса
  на HTTP-краю своё, `entities.OrderStatus` наружу не торчит (как `PanelSheetKindBody` ↔
  `PanelSheetKind`). Контроллер переводит между швами; алиасы импортов симметричны:
  `app_dtos`/`api_dtos`, `api_schemas`; вне контроллера — голые `dtos`, как в hex_arch.
- `Decimal` в JSON pydantic v2 сериализует **строкой** (`"19.99"`) — это часть контракта
  (раздел 5), в `*Response` — `examples=["19.99"]`.

### 4.4. Ошибки

`application/errors.py` без метакласса (hex_arch `ErrorMeta` выводит код из имени класса —
делаем то же через `__init_subclass__`):

```python
class Error(Exception):
    message_template: ClassVar[str] = "Ошибка приложения"
    code: ClassVar[str]  # snake_case от имени класса (__init_subclass__)

    def __init__(self, **context: object) -> None:
        self.context = context
        self.message = self.message_template.format_map(context)
        super().__init__(self.message)  # str(exc) и трассировки — с текстом


class NotFoundError(Error): ...  # категории → HTTP-статус


class ConflictError(Error): ...


class RuleViolationError(Error): ...


class StorageUnavailable(Error):
    message_template = "Хранилище временно недоступно, повторите попытку"


class CustomerNotFound(NotFoundError):
    message_template = "Клиент с id {id} не найден"


class CustomerAlreadyExists(ConflictError):
    message_template = "Клиент с email {email} уже существует"


class ProductNotFound(NotFoundError): ...


class OrderNotFound(NotFoundError): ...


class InsufficientStock(RuleViolationError):
    message_template = (
        "Товара {product_id} недостаточно: запрошено {requested}, доступно {available}"
    )


class OrderTransitionNotAllowed(RuleViolationError):
    message_template = "Заказ {id} в статусе {status}: действие «{action}» недопустимо"
```

`error_handlers.py` отображает **категории**, а не каждый класс (в interactive_panels —
цепочка `isinstance` на каждую ошибку; у нас новая ошибка не трогает адаптер):
`NotFoundError → 404`, `ConflictError → 409`, `RuleViolationError → 400`,
`StorageUnavailable → 503` + `Retry-After: 1`, прочие `Error → 500` (ошибка без категории —
дефект, он должен быть виден), `RequestValidationError → 400`, `Exception → 500` (с логом).

**Единая форма тела ошибки** `{"error": message, "code": code, "context": {...}}` — одна модель
`ErrorResponse` в `api/dtos.py`; ошибка валидации запроса отдаётся в той же форме:
`code="validation_error"`, `context={"details": [{loc, msg, type}, ...]}` (только эти три поля —
в `ctx` pydantic кладёт объекты исключений). `content` прогоняется через
`fastapi.encoders.jsonable_encoder` (в `context` бывает `Decimal`). Регистрация — вложенными
функциями `@app.exception_handler(errors.Error)` внутри `register_error_handlers(app)`:
так `mypy --strict` проходит без `# type: ignore[arg-type]`, который нужен образцу.

### 4.5. Настройки — у того, кто их потребляет

- `adapters/database/settings.py`: `POSTGRES_USER`, `POSTGRES_PASSWORD: SecretStr`,
  `POSTGRES_DB`, `POSTGRES_HOST="localhost"`, `POSTGRES_PORT=5432`, `POSTGRES_ECHO_SQL=False`,
  свойство `database_url` (`postgresql+asyncpg://…`), `extra="ignore"`. `env_file` задаётся
  **путём от файла пакета** (как в hex_arch), а не относительно CWD («CWD gotcha»
  interactive_panels); отсутствующий файл (в Docker `.env` не копируется) — не ошибка, значения
  приходят из окружения. В compose хост переопределяется `environment: POSTGRES_HOST: postgres`
  у `api` **и** `migrate` (hex_arch: `DATABASE_HOST: "db"`).
- `launchers/config.py`: `Settings(BaseSettings)` с `LOG_LEVEL="INFO"`,
  `DISCOUNT_MIN_QUANTITY=10`, `DISCOUNT_PERCENT=Decimal("5")` — правило слоя launchers
  «внешние источники конфигурации», бизнес-числа не зашиты в composition root.
- Отдельных настроек у API-адаптера нет (interactive_panels обходится без них): префикс —
  параметр `create_app(v1_prefix="/api/v1")`, `title` — литерал.
- Alembic-параметры (`script_location`, `version_locations`, `file_template`) — константы в
  `launchers/alembic_runner.py`, а не поля настроек (их никто не переопределяет через env);
  `alembic.ini` нет. `env.py` — **async** (образец `postgresql/alembic/env.py`:
  `async_engine_from_config` + `connection.run_sync(do_run_migrations)` + `asyncio.run`),
  `timezone` не задаём.
- Тесты: `tests/integration/database/conftest.py` держит крошечный `TestSettings(BaseSettings)`
  с тем же `env_file` и полем `TEST_DATABASE_URL: str | None = None` → `.env` работает и для
  тестов, прод-настройки тестовыми полями не засоряются (pydantic-settings **не** экспортирует
  `.env` в `os.environ`, поэтому `os.environ.get` не подошёл бы).

### 4.6. Composition root — `launchers/api.py`

```python
from orders_service.adapters import api
from orders_service.adapters import database
from orders_service.application import entities, services
from orders_service.launchers import config


class Settings:
    db = database.Settings()
    app = config.Settings()


class Logger:
    logging.basicConfig(level=Settings.app.LOG_LEVEL)  # uvicorn настраивает только свои логгеры


class Adapters:
    db = database.Database(settings=Settings.db)
    uow_factory = database.UnitOfWorkFactory(session_factory=db.session_factory)


class Application:
    # Выбор стратегии скидки — здесь (composition root), параметры — из настроек.
    discount_policy = entities.VolumeDiscount(
        min_quantity=Settings.app.DISCOUNT_MIN_QUANTITY,
        percent=Settings.app.DISCOUNT_PERCENT,
    )
    customer = services.Customer(uow_factory=Adapters.uow_factory)
    product = services.Product(uow_factory=Adapters.uow_factory)
    order = services.Order(uow_factory=Adapters.uow_factory, discount_policy=discount_policy)


class Controllers:
    v1_controller = api.V1Controller(
        customer=Application.customer, product=Application.product, order=Application.order
    )


lifespan = api.create_lifespan(setup=[Adapters.db.aopen], cleanup=[Adapters.db.aclose])
app = api.create_app(v1_controller=Controllers.v1_controller, lifespan=lifespan)
```

`api.V1Controller` — алиас `Controller` из `v1`, экспортируемый пакетом `adapters/api`
(как в образце `from .v1 import Controller as V1Controller`). Это и есть главное условие
пользователя: обработчики — методы `Controller` в API-адаптере, сервисы приходят в его
конструктор из composition root, как в любой другой адаптер. `create_app(*, v1_controller,
v1_prefix="/api/v1", lifespan=None)`: `title="Orders Service API"`, `version`, `openapi_tags`
для трёх тегов; CORS **не** добавляем (фронта нет — записано как сознательное отличие).
Никакого DI-контейнера и `Depends()` — зависимости собираются вручную при импорте модуля
(оба образца). Второй launcher — `alembic_runner.py`
(`python -m orders_service.launchers.alembic_runner upgrade head`), тоже с `basicConfig`.

---

## 5. Контракт API (`/api/v1`) и словарь имён

| Метод и путь | Метод `Controller` → `operation_id` | Тело / параметры | Ответ | Ошибки |
|---|---|---|---|---|
| `POST /customers` | `create_customer` → `createCustomer` | `CustomerCreateBody{name, email}` | 201 `CustomerResponse` | 400, 409 |
| `GET /customers/{customer_id}` | `get_customer` → `getCustomerById` | — | 200 `CustomerResponse` | 404 |
| `POST /products` | `create_product` → `createProduct` | `ProductCreateBody{name, price, stock}` | 201 `ProductResponse` | 400 |
| `GET /products/{product_id}` | `get_product` → `getProductById` | — | 200 `ProductResponse` | 404 |
| `POST /orders` | `place_order` → `placeOrder` | `OrderCreateBody{customer_id, lines: [OrderLineCreateBody{product_id, quantity}]}` | 201 `OrderResponse` | 400 (нехватка остатка, дубли товаров), 404 (клиент/товар) |
| `GET /orders/{order_id}` | `get_order` → `getOrderById` | — | 200 `OrderResponse` | 404 |
| `GET /orders` | `list_orders` → `listOrders` | `customer_id?`, `status?: api_schemas.OrderStatus`, `limit` (`Query(default=20, ge=1, le=200)`), `offset` (`ge=0`) | 200 `OrderListResponse{items}` | 400 |
| `POST /orders/{order_id}/pay` | `pay_order` → `payOrder` | — | 200 `OrderResponse` | 404, 400 (недопустимый переход) |
| `POST /orders/{order_id}/cancel` | `cancel_order` → `cancelOrder` | — | 200 `OrderResponse` | 404, 400 |
| `GET /healthcheck` | `healthcheck` (`include_in_schema=False`) | — | 200 `{"status": "ok"}` | — |

Все ошибки — `ErrorResponse{error, code, context}`; 503 `StorageUnavailable` возможен на любой
ручке с БД. Деньги (`price`, `unit_price`, `discount`, `subtotal`, `total`) — строки с двумя
знаками (`"19.99"`). Теги: `v1: Customers`, `v1: Products`, `v1: Orders`; общие карты
`responses` (400/404/409/500/503) объявляются в `create_router` как в образце; `summary` у
каждой ручки. Swagger — штатный `/docs`.

**Словарь имён (сквозной, попадает в README):**

| Понятие | `entities` | `dtos` (вход / выход) | `services` | `interfaces` → `database` | `api/v1/schemas` → `api/v1/dtos` |
|---|---|---|---|---|---|
| Клиент | `Customer` | `NewCustomerInfo` / `Customer` | `Customer.add/get` | `CustomersRepo` | `CustomerCreateBody` → `CustomerResponse` |
| Товар | `Product` (`reserve/release`) | `NewProductInfo` / `Product` | `Product.add/get` | `ProductsRepo` | `ProductCreateBody` → `ProductResponse` |
| Заказ | `Order` (`apply_discount/pay/cancel`), `OrderLine`, `OrderStatus` | `NewOrderInfo{lines: [NewOrderLineInfo]}`, `FindOrders` / `Order{lines: [OrderLine]}` | `Order.place/get/find/pay/cancel` | `OrdersRepo` | `OrderCreateBody{lines: [OrderLineCreateBody]}`, `OrderStatus` → `OrderResponse{lines: [OrderLineResponse]}`, `OrderListResponse` |
| Транзакция | — | — | `@transactional` (`application/transactional.py`), `uow` — первый после `self` | `UnitOfWork`, `UnitOfWorkFactory` → `database.UnitOfWork`, `database.UnitOfWorkFactory` | — |
| Ошибки | — | — | — | `errors.Error` → категории → `CustomerNotFound` … | `api/dtos.py: ErrorResponse` |

Правила одной строкой: одинаковое имя в разных модулях различается модулем; суффиксы
`*Body`/`*Response` — только на HTTP-краю; `New*Info` — входные DTO ядра; `Find*` — параметры
поиска.

---

## 6. SOLID — где именно

| Принцип | Где видно |
|---|---|
| **S** | Сервис = сценарии одной сущности; репозиторий = персистентность одной сущности; UoW = граница транзакции; `Controller` = перевод HTTP ↔ DTO; `router.py` = маршрутизация; `error_handlers.py` = ошибки → HTTP; `@transactional` = один сквозной аспект |
| **O** | Новая политика скидки — новый класс `DiscountPolicy` без правки `services.Order`; новый статус заказа — новый класс State и строка в `_STATES`; новое хранилище — новая реализация `UnitOfWorkFactory`/репозиториев; новая ошибка — наследник категории, адаптер ошибок не меняется |
| **L** | Любая реализация портов (SQLAlchemy, `Mock(spec=…)` в тестах) подставляется вместо абстракции; все State-классы выполняют контракт базового (либо переход, либо `OrderTransitionNotAllowed`) |
| **I** | Три узких порта репозиториев вместо одного «универсального» `Repo[T]`; порт `UnitOfWork` без `rollback()` (нужен только реализации); `UnitOfWorkFactory` отделён от `UnitOfWork`. **Сознательный компромисс:** один `UnitOfWork` на три репозитория — `services.Customer` получает порт, две трети которого не использует; UoW-порты по агрегатам (как `PanelStructureUnitOfWork` / `PanelGraphUnitOfWork` в interactive_panels) для примера на три сущности — лишние, это честно записывается в README |
| **D** | `application` зависит только от `interfaces`; адаптеры реализуют порты; направление сборки — launcher; выбор конкретной `DiscountPolicy` — в composition root, параметры — из настроек |

---

## 7. Паттерны — карта

| Паттерн | Класс | Где |
|---|---|---|
| Abstract Factory (GoF) | `interfaces.UnitOfWorkFactory` → `database.UnitOfWorkFactory.create()` создаёт семейство связанных объектов одной транзакции: сессию, три репозитория на ней, UoW | `application/interfaces/unit_of_work.py`, `adapters/database/unit_of_work.py` |
| Strategy (GoF) | `DiscountPolicy`: `NoDiscount`, `VolumeDiscount`; контекст — `entities.Order.apply_discount(policy)`, выбор — launcher | `application/entities.py` |
| State (GoF) | `Order.pay()/cancel()` делегируют объекту состояния (`_NewOrderState`, `_FinalOrderState`, stateless, по `status`); недопустимый переход — исключение | `application/entities.py` |
| Adapter (GoF, в широком смысле) | Реализации портов: репозитории и UoW адаптируют `AsyncSession` к контрактам `interfaces.*` | `adapters/database/` |
| Метод-обёртка `@transactional` — Python-декоратор / аспект (**не** GoF Decorator: меняет сигнатуру и применяется статически) | аналог `DecoratedFunction` + `TransactionContext` из hex_arch | `application/transactional.py` |
| Null Object (не GoF — Woolf/PLoP) | `NoDiscount` | `application/entities.py` |
| Repository, Unit of Work, DTO (PoEAA, **не GoF**) | порты + реализации | `interfaces/`, `adapters/database/` |
| Composition Root | `launchers/api.py` | `launchers/` |

Снято после ревью как натянутое: «Decorator (GoF)» для обёртки, «Facade» для сервисов и
контроллера, «Adapter» для всего слоя `adapters`. Маркер «Паттерн: X (GoF)» ставится в
докстринге класса-носителя (как «Паттерн стратегия» у `_ItemReviewStrategySelector` в hex_arch);
README ссылается на эти классы.

---

## 8. Сознательные отличия от hex_arch

| hex_arch | Здесь | Почему |
|---|---|---|
| Falcon + gunicorn/gevent, sync SQLAlchemy, psycopg2 | FastAPI + uvicorn, async SQLAlchemy, asyncpg | требование пользователя; inbound по interactive_panels (async) |
| `TransactionContext` (ContextDecorator, сессия на поток, счётчик вложенности) + `DecoratedFunctionRegistry.apply_decorators(DB.context)` в launcher | `UnitOfWorkFactory` в конструкторе сервиса + `@transactional` в `application/transactional.py` | требование: UoW объединяет репозитории и создаётся в сервисе при вызове; thread-local не живёт в asyncio; глобальная накопительная мутация классов реестром — лишняя сложность, счётчик вложенности не нужен |
| Репозитории — синглтоны launcher'а с сессией из контекста | Репозитории создаются фабрикой UoW на каждую транзакцию | то же требование |
| `application/schemas` (параметры поиска) | `FindOrders` в `dtos/order.py` | один класс; слово `schemas` занято API-швом interactive_panels с другим смыслом |
| Pydantic v1 (`from_orm`, `validate_arguments` на методах) | Pydantic v2 (`model_validate(from_attributes)`), без `validate_call` | актуальная версия; `validate_call` поверх обёртки с инжектом `uow` ломается о `__wrapped__`-сигнатуру; решение пользователя — раздел 13 |
| `ErrorMeta` (метакласс, namespaces) | `__init_subclass__` + категории ошибок | меньше магии; категории дают OCP в error-handler'е |
| Стратегия поиска `_XStrategySelector` → 2ⁿ методов репозитория | один `OrdersRepo.fetch_all(filter_params)` с динамическим `WHERE` | Strategy показана на скидке; 2ⁿ методов — демонстрация «разнообразия подходов» hex_arch, в малом примере это шум |
| Миграции в entrypoint API | one-shot контейнер `migrate`, API `depends_on: service_completed_successfully` | interactive_panels; API никогда не мигрирует сам |
| `adapters/log` с JSON-форматтером | `logging.basicConfig(level=LOG_LEVEL)` в launcher'ах | минимум; без него `logger.exception` в обработчике 500 уходит в `lastResort`; пересмотрено в разделе 18 |
| Без линтера, `.editorconfig` на 90 символов | ruff (`line-length = 100`, `line-ending = "lf"`) + mypy `strict` (конфиг из interactive_panels), `.editorconfig` с `end_of_line = lf` | типизация обёртки — часть демонстрации; LF — иначе на Windows ломаются shebang/скрипты в контейнерах |
| Комментарии и докстринги | на русском, идентификаторы на английском | оба образца |

---

## 9. Инфраструктура и документация

- **pyproject.toml**: `requires-python = ">=3.12"`; deps: `fastapi`, `uvicorn[standard]`,
  `sqlalchemy[asyncio]>=2.0.36` (extra обязателен — greenlet), `asyncpg`, `alembic`,
  `pydantic-settings`; dev: `pytest`, `pytest-asyncio` (`asyncio_mode = "auto"`), `httpx`, `ruff`,
  `mypy`. `[tool.pytest.ini_options] pythonpath = ["."]`. `[tool.ruff]` — как в interactive_panels
  (`E,F,I,UP,B,RUF,ANN,S`, `RUF001-3` выключены из-за кириллицы, `S101` разрешён в тестах,
  `line-length = 100`), `UP046/UP047` **не** игнорируем — PEP 695 используется;
  `[tool.ruff.format] line-ending = "lf"`. `[tool.mypy] strict = true`, плагин pydantic,
  проверяется весь проект включая `tests/` (поэтому тесты с полными аннотациями).
- **Dockerfile** (`deployment/Dockerfile`): builder (`uv sync --frozen --no-install-project --no-dev`)
  → runtime (`python:3.12-slim`, non-root `app`, `COPY orders_service/`, `PATH` на `.venv/bin`),
  `CMD uvicorn orders_service.launchers.api:app --host 0.0.0.0 --port 8000`.
- **docker-compose.yml** (корень; `docker compose up -d --build`):
  - `postgres` (`postgres:17-alpine`, healthcheck `pg_isready`, volume, порт `${POSTGRES_PORT:-5432}`,
    `deployment/postgres/init-test-db.sql` → `CREATE DATABASE orders_test;` — выполняется
    **только при первой инициализации volume**, это пишется в README);
  - `migrate` (тот же образ, `python -m orders_service.launchers.alembic_runner upgrade head`,
    `depends_on: postgres: service_healthy`, `restart: "no"`);
  - `api` (порт `${APP_PORT:-8000}:8000`, `depends_on: migrate: service_completed_successfully`,
    healthcheck через `python -c "urllib.request.urlopen(...)"` — в slim-образе нет `curl`);
  - у `api` и `migrate`: `env_file: .env` **и** `environment: POSTGRES_HOST: postgres`.
- **.env.example**: `POSTGRES_USER=orders`, `POSTGRES_PASSWORD=orders`, `POSTGRES_DB=orders`,
  `POSTGRES_HOST=localhost`, `POSTGRES_PORT=5432`, `APP_PORT=8000`, `LOG_LEVEL=INFO`,
  `DISCOUNT_MIN_QUANTITY=10`, `DISCOUNT_PERCENT=5`,
  `TEST_DATABASE_URL=postgresql+asyncpg://orders:orders@localhost:5432/orders_test`.
- **Политика докстрингов** (ruff `D` не включаем — это соглашение): обязательны у методов портов
  (одна строка), публичных методов сервисов (сценарий + какие `errors.*` поднимает), поведения
  сущностей (`reserve/release/apply_discount/pay/cancel`), `transactional`, обоих `UnitOfWork`,
  и модульные — у `entities.py`, `transactional.py`, `unit_of_work.py`, `error_handlers.py`,
  `launchers/api.py`; маркер «Паттерн: X (GoF)» — в докстринге класса-носителя. Не нужны
  (шум): листовые классы ошибок (`message_template` самодокументирует), API-модели
  (`Field(description=…)` идёт в Swagger), методы контроллера (`summary` в роутере), тесты.
- **README.md** — разделы: (1) запуск (compose / локально `uv run uvicorn … --reload` поверх
  compose-postgres) и команды (`uv sync`, `uv run ruff check .`, `uv run ruff format .`,
  `uv run mypy .`, `uv run pytest`); (2) слои и направление зависимостей — mermaid-диаграмма
  пакетов (`launchers → adapters → application`); (3) путь запроса `POST /orders` — mermaid
  `sequenceDiagram` (HTTP → `Controller` → `services.Order.place` → `@transactional` → `UnitOfWork`
  → репозитории → сущности → DTO → `OrderResponse`) — главный артефакт примера про UoW;
  (4) правило транзакций (граница = публичный метод, без вложенности, commit делает обёртка);
  (5) `stateDiagram` статусов заказа; (6) словарь имён (раздел 5); (7) таблицы SOLID и
  паттернов (разделы 6–7) со ссылками на классы; (8) контракт ошибок (категория → код, форма
  тела); (9) чек-лист «как добавить сценарий» (порт → репозиторий → метод сервиса с
  `@transactional` → контроллер → `add_api_route` → тесты); (10) тесты: раскладка и правило skip
  без `TEST_DATABASE_URL`; (11) e2e-сценарий curl'ом (клиент → товар → заказ → оплата / отмена
  с возвратом остатка); (12) «что сознательно не сделано» и глоссарий отличий от hex_arch
  (`TransactionContext → UnitOfWork`, раздел 8).

---

## 10. Тест-план

Стиль: плоские `async def test_*` с полными аннотациями (ruff `ANN` действует и на тесты,
mypy проверяет `tests/`), моки в фикстурах `conftest.py`; проверки через `method_calls`/
`mock_calls` (стиль hex_arch) остаются. **Критерий «не холостой тест»:** каждый тест падает,
если убрать проверяемую ветку.

**Unit (без БД), `tests/unit/application/`** — приоритет 1. Фикстуры в `conftest.py`
(поведение проверено, раздел 14):

```python
@pytest.fixture
def uow() -> MagicMock:
    uow = MagicMock(spec=interfaces.UnitOfWork)
    uow.__aenter__.return_value = uow  # иначе `async with` отдаст другой объект
    uow.customers = Mock(interfaces.CustomersRepo)  # spec в property не протаскивается —
    uow.products = Mock(interfaces.ProductsRepo)  # репозитории присваиваются явно
    uow.orders = Mock(interfaces.OrdersRepo)
    return uow


@pytest.fixture
def uow_factory(uow: MagicMock) -> Mock:
    factory = Mock(interfaces.UnitOfWorkFactory)
    factory.create.return_value = uow
    return factory
```

`Mock(spec=ABC)` даёт `AsyncMock` для `async def`; `uow.mock_calls` показывает транзакцию целиком:
`[call.__aenter__(), call.customers.fetch_by_id(1), …, call.commit(), call.__aexit__(None, None, None)]`.
Рукописные фейки не нужны.

1. `test_entities.py`: `Product.reserve` уменьшает остаток / поднимает `InsufficientStock`
   с контекстом; `release`; `Order.subtotal/total/total_quantity`; `apply_discount` с
   `NoDiscount` и `VolumeDiscount` (порог включительно, ниже порога, округление до копеек);
   State: `new→paid`, `new→cancelled`, `paid→cancel`, `cancelled→pay`, `paid→pay` →
   `OrderTransitionNotAllowed`; `created_at` не участвует в `__eq__`.
2. `test_transactional.py` (обёртка на игрушечном сервисе с `uow_factory`): нормальный возврат →
   `uow.mock_calls == [call.__aenter__(), call.commit(), call.__aexit__(None, None, None)]`;
   исключение в методе → `commit` не вызван, `__aexit__` получил именно это исключение
   (`assert_called_once_with(type(err), err, ANY)`), исключение прошло наружу; исключение в
   `commit()` → прошло наружу и попало в `__aexit__`; два вызова → `factory.create.call_count == 2`
   (новый UoW на вызов). Каждый тест падает при удалении соответствующей ветки обёртки.
3. `test_order.py` (и `test_customer.py`, `test_product.py`): `method_calls` репозиториев и
   `uow.mock_calls` (порядок: клиент → товары `for_update=True` → `orders.add(entities.Order(...))`
   → `commit`); маппинг в DTO; `CustomerNotFound`/`ProductNotFound` (один отсутствующий из
   нескольких); `InsufficientStock` на второй строке → `commit` не вызван; `cancel` возвращает
   остатки (`fetch_by_ids(..., for_update=True)` + `release`); `pay` из `paid` → ошибка;
   `Customer.add` при занятом email → `CustomerAlreadyExists`, `add` репозитория не вызван.

**HTTP (контроллер + роутер + error handlers, без БД), `tests/integration/api/`** — приоритет 1:

4. `conftest.py`: `create_app(v1_controller=Controller(customer=Mock(services.Customer), …))` +
   `httpx.AsyncClient(transport=ASGITransport(app))`. Тесты: коды и тела всех ручек;
   `NotFoundError → 404`, `ConflictError → 409`, `RuleViolationError → 400`, `StorageUnavailable →
   503` с `Retry-After`; невалидное тело → 400 с `code="validation_error"` и `details`; `Decimal`
   в ответе — строка; `method_calls` сервиса содержит ровно ожидаемый DTO
   (как `assert patient_service.method_calls == [call.add(new_patient_info)]` в hex_arch).

**Integration (реальный Postgres), `tests/integration/database/`** — приоритет 2,
`skip`, если `TestSettings().TEST_DATABASE_URL` пуст:

5. `conftest.py`: engine из `TEST_DATABASE_URL`, импорт пакета `database` (регистрация маппинга),
   `metadata.create_all` на сессию (hex_arch), `TRUNCATE … RESTART IDENTITY CASCADE` после
   каждого теста (UoW коммитит по-настоящему), `drop_all` в конце; настоящая
   `database.UnitOfWorkFactory`.
6. `test_unit_of_work.py`: оформление заказа пишет заказ, строки и уменьшает остатки
   **атомарно**; нехватка остатка на второй строке → в БД нет ни заказа, ни изменения остатка
   первого товара (главная демонстрация UoW); отмена возвращает остатки; `IntegrityError` по
   email → `CustomerAlreadyExists`; **детерминированная гонка** на последнюю единицу: задача A
   через репозиторий берёт товар `for_update=True` и ждёт `asyncio.Event`, задача B вызывает
   `services.Order.place` и блокируется на строке, A резервирует и коммитит, событие
   отпускается — B получает `InsufficientStock`, остаток 0 (проверка, что `FOR UPDATE` реально
   держит); **перекрёстный порядок товаров** (`place` [1, 2] параллельно `cancel` заказа на
   [2, 1]) завершается без дедлока благодаря `ORDER BY id` в запросе.
7. `test_repositories.py`: `fetch_all(FindOrders)` фильтрует по `customer_id`/`status`,
   лимит/смещение, порядок по `id`.

**Необязательно (если останется время):** проверка, что `alembic` autogenerate не видит
расхождений между `tables.py` и миграцией.

---

## 11. Этапы реализации и критерии готовности

0. Каркас: удалить `main.py`; `pyproject.toml`, `.python-version`, `.editorconfig`,
   `.gitattributes`, `.gitignore`, `.dockerignore`, `.env.example`; `uv sync`.
1. Ядро: `entities.py` (+ State, Strategy), `errors.py`, `interfaces/`, `dtos/`, `transactional.py`,
   `services/`, `__init__.py` с `__all__`. → unit-тесты 1–3 зелёные, `mypy --strict` чист.
2. Outbound: `settings.py`, `database.py`, `tables.py`, `mapping.py` (+ импорт в `__init__`),
   `repositories/`, `unit_of_work.py`, async `alembic/env.py` + `script.py.mako`,
   `launchers/alembic_runner.py`, миграция `0001_initial` (autogenerate на compose-postgres +
   ручная правка).
3. Inbound: `v1/schemas`, `v1/dtos`, `controller.py`, `router.py`, `app.py`, `lifespan.py`,
   `error_handlers.py`, `dtos.py`. → HTTP-тесты 4 зелёные.
4. `launchers/config.py`, `launchers/api.py`; локальный запуск
   `uv run uvicorn orders_service.launchers.api:app --reload`.
5. Deployment: Dockerfile, compose, `init-test-db.sql`; `docker compose up -d --build` →
   миграции применены, `/docs` открывается, e2e-сценарий из README проходит curl'ом.
6. Integration-тесты 5–7 на compose-postgres (`orders_test`).
7. README (раздел 9).
8. Контрольная точка по правилам ревью: ревью **реализации** двумя независимыми рецензентами
   после зелёных `ruff`/`mypy`/`pytest`, до e2e-отчёта.

Готово = `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`,
`uv run pytest` зелёные; стенд поднимается одной командой; e2e из README воспроизводится.
Коммиты — только по явной просьбе (репозиторий пока не инициализирован).

---

## 12. Отклонённые альтернативы

- **Реестр `DecoratedFunctionRegistry` + `apply_decorators(...)` в launcher** (hex_arch).
  Отклонено: глобальная и накопительная мутация классов при сборке; thread-local сессия не
  живёт в asyncio; счётчик вложенности — лишняя сложность; требование «прокинуть в сервисные
  классы» естественнее читается как конструкторная зависимость. (Довод v1 «без
  `apply_decorators` метод не вызвать» снят как круговой: в hex_arch необёрнутый метод
  вызывается, невозможность вызова — следствие инжекта `uow`, то есть нашего решения.)
- **Порт `UnitOfWork.transaction() -> Transaction`** (синглтон-UoW, как `PanelStructureUnitOfWork`
  в interactive_panels; предложено ревью). Отклонено: по Фаулеру UoW — объект одной бизнес-
  транзакции, то есть создаваемый на вызов, и именно так сформулировал пользователь
  («создавать объект UoW … при вызове»); явный `commit()` в обёртке делает границу видимой в
  одном месте. Принято из предложения: создавать сессию и репозитории до входа в контекст
  (в фабрике), убрать `rollback()` из порта.
- **Один долгоживущий объект UoW в сервисе** (`async with self.uow:` по cosmic python).
  Отклонено: небезопасно при конкурентных запросах (сессия в `self`).
- **Рукописные `FakeUnitOfWork`/`FakeUnitOfWorkFactory`** для unit-тестов. Отклонено:
  `MagicMock(spec=interfaces.UnitOfWork)` + `Mock(interfaces.XRepo)` даёт то же и показывает всю
  транзакцию в `uow.mock_calls`; меньше кода в тестах, стиль hex_arch.
- **FastAPI `Depends()` для сессии/UoW.** Отклонено: оба образца принципиально без DI-контейнера.
- **Core-запросы + DTO из репозиториев** (interactive_panels). Отклонено: пользователь просил
  архитектуру hex_arch — сущности-dataclass'ы с императивным маппингом.
- **Пропагация транзакции** (`uow=` передаётся явно и обёртка присоединяется к внешней).
  Отклонено как YAGNI; правило «публичный метод = граница» проще.
- **`adapters/inbound/api` + `adapters/outbound/database`** (как в interactive_panels; было в
  v1–v2). Отклонено после ответа пользователя: при одном входящем и одном исходящем адаптере
  это лишний уровень путей, а плоская раскладка — буквально hex_arch. Главное условие
  («обработчики в API-адаптере, чистый DI») от раскладки не зависит.
- **Два тела ошибок** (`ErrorResponse` и `ValidationErrorResponse`). Отклонено в пользу единой
  формы `{error, code, context}` — одна модель, без `Optional`-супа.

---

## 13. Решения (утверждено пользователем 2026-10-09)

- **`validate_call` на методах сервисов — нет** (ответ пользователя): вход валидируется при
  построении DTO на границе; правило hex_arch о валидации на публичных методах сознательно
  не переносится.
- **Форма State — делегировано мне:** GoF State из абстрактного `_OrderState` и двух конкретных
  состояний (`_NewOrderState`, `_FinalOrderState`). Таблица переходов отклонена как менее
  явная: магические строки действий и нет точки расширения «новый статус = новый класс».
- **Раскладка адаптеров — плоская** (`adapters/api`, `adapters/database`), как в hex_arch.
- **Главное условие пользователя:** обработчики FastAPI определяются в API-адаптере (методы
  `Controller`), зависимости — через конструктор, как у всех сервисов и адаптеров;
  `Depends()` не используется.
- Принято по умолчанию (возражений не было): плоская раскладка проекта; пакет `orders_service`;
  Python 3.12 (локально стоит 3.14 — uv скачает 3.12); удалить шаблонный `main.py`; git не
  инициализировать, пока не попросят; `FindOrders` в `dtos` без пакета `schemas`;
  `docker-compose.yml` в корне; параметры скидки из `.env`.

---

## 14. Результаты адверсариального кросс-ревью плана v1

**Состав.** Два независимых рецензента (субагенты со свежим контекстом), по просьбе
пользователя — оба по архитектуре и чистоте кода: (А) соответствие hex_arch / interactive_panels,
SOLID, GoF, полнота; (Б) чистота кода, дизайн модулей, имена, тесты как код, дидактика.
Рецензент по корректности был запущен и остановлен по просьбе пользователя («корректность не
обязательна»); его вопросы (семантика обёртки, типизация, маппинг, моки) частично закрыл сам —
см. «Самопроверка». Оба рецензента — только чтение; эксперименты — в scratchpad.

**Итог.** BLOCKER — 0. А: 5 MAJOR, 11 MINOR, 6 NIT. Б: 6 MAJOR, 17 MINOR, 6 NIT.
Совпавшие у обоих (сильный сигнал): `self, /` в обёртке; «фабрика создаёт семейство» расходится
с кодом (репозитории в `__aenter__`); `TEST_DATABASE_URL` никем не читается;
`super().__init__(message)` в `Error`; аннотации `__aexit__`; `tests/support` вне дерева;
`Decimal` строкой в JSON; `API_TITLE` не используется / `api = api.Settings()` затеняет модуль.

**Принято (все MAJOR и большинство MINOR/NIT) — внесено в v2:**

- Типизация обёртки: `self: S, /` + PEP 695 (4.1); правило `Mock(spec)`, не `create_autospec`.
- Фабрика создаёт сессию + три репозитория + UoW (все атрибуты в `__init__`); `rollback()`
  убран из порта; перевод ошибок СУБД — в `__aexit__` реализации → `StorageUnavailable` (503).
- Порядок блокировок — `ORDER BY id` в запросе `FOR UPDATE`; `ORDER BY id` в `fetch_all`;
  тест на перекрёстный порядок и детерминированная гонка через `asyncio.Event`.
- Регистрация маппинга импортом пакета адаптера; async `alembic/env.py`; константы Alembic
  в runner'е.
- Карта паттернов: сняты Decorator (GoF), Facade, Adapter «для всего слоя»; Null Object
  помечен как не-GoF; Abstract Factory оставлен, но теперь честно соответствует коду.
- ISP: один UoW на три репозитория записан как сознательный компромисс (раздел 6).
- Ошибки: `super().__init__`, единая форма тела, `jsonable_encoder`, `details` только
  `loc/msg/type`, вложенные `@app.exception_handler` без `# type: ignore`.
- Убраны `application/schemas` (`FindOrders` → `dtos`), `application/utils`
  (`transactional.py` — модуль слоя), `api/settings.py`; добавлен `launchers/config.py`
  (`LOG_LEVEL`, `DISCOUNT_*`); `logging.basicConfig` в launcher'ах (пересмотрено в разделе 18).
- Имена: `services.Order.place` vs `entities.Order.apply_discount` (без дубля глаголов);
  `Controllers.v1_controller`; единое число для предметных модулей; сквозной словарь имён
  (раздел 5); API-перечисление статуса; методы контроллера названы.
- Тесты: `MagicMock(spec=UnitOfWork)` вместо фейков (с обязательным
  `__aenter__.return_value = uow`), холостой тест «`rolled_back is True`» заменён проверкой
  аргументов `__aexit__` и `commit`; `TestSettings` для `TEST_DATABASE_URL`; `pythonpath`;
  стиль тестов с аннотациями; `created_at` с `compare=False`.
- Инфраструктура: `.editorconfig`/`.gitattributes`/`line-ending = "lf"` (CRLF на Windows ломал
  бы init-скрипт), `init-test-db.sql` вместо `.sh`, compose в корне, `env_file` +
  `POSTGRES_HOST` у `api` и `migrate`, healthcheck через `python -c`, замечание про первую
  инициализацию volume, `sqlalchemy[asyncio]`.
- README: диаграммы (пакеты, sequence `POST /orders`, state), словарь имён, контракт ошибок,
  чек-лист добавления сценария, политика докстрингов; `docs/plan.md` — история проектирования.
- `__init__.py` с `__all__`; довод v1 против реестра исправлен (был круговой).

**Отклонено (с мотивом — раздел 12):** порт `UnitOfWork.transaction() -> Transaction` (А);
рукописные фейки UoW (Б, после проверки `MagicMock`); два тела ошибок (А). Плоская раскладка
адаптеров (Б) в v2 была отклонена, после ответа пользователя — принята (раздел 13). Разногласие А (параметры скидки из env) ↔ Б (константы с
комментарием) решено в пользу env по правилу слоя launchers.

**Вынесено пользователю (раздел 13):** `validate_call` (А), форма State (А и Б) — решено
2026-10-09, см. раздел 13.

**Самопроверка в scratchpad (на этапе плана, без рецензента по корректности):**
- `mypy --strict`: эскиз v1 падал на `_Wrapped` от `functools.wraps`; с `self, /` — чисто и в
  TypeVar-, и в PEP 695-форме; `reveal_type` = `def (order_id: int) -> Awaitable[str]`; ловятся
  `arg-type`, `call-arg`, класс без `uow_factory`.
- SQLite + aiosqlite: императивный маппинг `kw_only`-dataclass'ов на `AsyncSession`, autobegin,
  `flush` → id, `lazy="selectin"` без `MissingGreenlet`, `model_validate(from_attributes=True)`
  с `@property` и вложенным списком, доступ к атрибутам после commit при
  `expire_on_commit=False`; `Decimal` → `"18.50"` в JSON; без `sqlalchemy[asyncio]` импорт
  `sqlalchemy.ext.asyncio` падает (greenlet).
- `MagicMock(spec=UnitOfWork)`: `__aexit__` возвращает `False` (исключения не глотаются),
  `__aenter__` по умолчанию возвращает **другой** объект (нужно `return_value = uow`),
  spec не протаскивается в property-репозитории; на успешном пути `mock_calls` =
  `[__aenter__, repo.fetch, commit, __aexit__(None, None, None)]`, при исключении `commit` не
  вызван, `__aexit__` получил исключение.

---

## 15. Результаты адверсариального кросс-ревью реализации (2026-10-10)

**Состав.** Два независимых рецензента (только чтение; `ruff`/`mypy`/`pytest` и эксперименты
в scratchpad разрешены): (А) архитектура и чистота кода — 0 BLOCKER, 2 MAJOR, 10 MINOR, 9 NIT;
(Б) корректность — 0 BLOCKER, 3 MAJOR, 7 MINOR, 8 NIT, с экспериментами на стенде (обрыв
соединения через `pg_terminate_backend`, дедлок, переполнение типов, мутационное тестирование
обёртки). Совпавшие находки: деньги в JSON без двух знаков, когда значение не прошло через БД.

**Принято и исправлено:**
- Обрыв соединения у asyncpg — `InterfaceError` с `connection_invalidated`, а не
  `OperationalError` (Б, MAJOR): `_is_transient` опирается на флаг `connection_invalidated`,
  `OperationalError`, `ConnectionError`/`gaierror`, `TimeoutError` пула и sqlstate 40001/40P01;
  `pool_pre_ping=True`; интеграционные тесты на обрыв соединения и дедлок (ветка sqlstate).
- Email с не-ASCII символами удлинялся при `to_lower` → 500 (Б, MAJOR): email только ASCII.
- Входы вне диапазона типов БД → 500 (Б, MAJOR): общие ограничения `dtos/base.py`
  (`MAX_INT32`, `MAX_LINE_QUANTITY`, `MAX_ORDER_LINES`, `MAX_PAGE_LIMIT`) у DTO ядра, `*Body`
  и `Path/Query`; `discount` — `Numeric(20, 2)`; тесты границ.
- Деньги строкой с двумя знаками всегда (А MAJOR, Б MINOR): тип `Money` с `PlainSerializer`
  в `api/v1/dtos`; `Decimal` в контексте ошибок — строкой (`custom_encoder`).
- Дублирование ограничений `*Body` ↔ DTO (А, MAJOR): `*Body` используют типы `dtos.base`,
  правило «один товар — одной строкой» — общая функция `ensure_one_line_per_product`;
  тест `test_schemas.py` держит инвариант «прошло `*Body` — принимает ядро».
- 404/405 маршрутизации — в едином теле (`code: http_error`); 503 логируется без трассировки;
  500 не логируется дважды (трассировку пишет сервер).
- `fetch_by_ids(for_update=True)` перечитывает строку (`populate_existing`) — под блокировкой
  состояние актуально даже после чтения без блокировки в той же транзакции; тест.
- Общий шаг `_lock_products` в `services/order.py` (поднимает `ProductNotFound`, в `cancel`
  вместо `KeyError`); `_is_transient` без мёртвого `pgcode` и без дубля кортежа в `__aexit__`;
  `UnitOfWork.__init__` принимает порты; имя ограничения email — из `constraint_name` asyncpg.
- Тесты: хелперы в `tests/integration/database/support.py` (без импорта `conftest`),
  `drop_all`/`create_all` на каждый тест, таймауты в гонках, честная формулировка теста
  «place + cancel без дедлока» и отдельный тест дедлока, успешный `pay` на реальной БД.
- Документация и имена: маркер Adapter в докстринках, оговорка «Abstract Factory в вырожденной
  форме», докстринги у всех методов портов, `FastApiWithout422`, `Settings.service`,
  `LOG_LEVEL.upper()`, CHECK на статус в БД (`create_constraint=True`), README: границы входа,
  404/405, `tables.x.c` в таблице отличий, чек-лист новой сущности, таблица тестов.

**Отклонено:** обработчик `pydantic.ValidationError` → 400 как страховка от дрейфа (А) —
маскировал бы ошибки сборки ответа как клиентские; дрейф закрыт общими типами и тестом.
Сборка `database.Database` в тестовом conftest (А) — его настройки требуют `POSTGRES_*`, тесты
живут одной строкой `TEST_DATABASE_URL`. Двойной `build:` в compose (Б, NIT) — второй раз из
кэша, как в образце.

**Расхождения текста плана v3 с кодом (код прав):** `__all__` есть у пакетов с экспортами,
пакеты-неймспейсы — с докстрингом; в `api/v1/schemas` и `api/v1/dtos` алиас `app_dtos` (как в
образце); `alembic/env.py` импортирует `tables`, что исполняет `__init__` пакета и регистрирует
маппинг — безвредно; отсутствующий товар выбирается в порядке запроса, а не `min(missing)`.
Добавлены файлы, которых нет в дереве §3: `application/dtos/base.py`, `api/v1/dtos/money.py`,
`tests/integration/api/test_schemas.py`, `tests/integration/database/support.py`.

**Итог после правок:** `ruff check`, `ruff format --check`, `mypy --strict` (78 файлов) — чисто;
`pytest` — 107 passed (интеграция с PostgreSQL включена); `alembic check` — схема без
расхождений с `tables.py`; e2e в Docker-стеке пройден.

**Повторный прицельный раунд (один рецензент по изменённым местам):** 0 BLOCKER, 3 MAJOR,
3 MINOR, 4 NIT. Принято и исправлено: порядок веток логирования (ветка «503 без трассировки»
была недостижима — проверяется `caplog`); `offset` ограничен int4 (`dtos.Offset`), иначе
переполнение int64 давало 500; встроенный `TimeoutError` (недоступный хост) считается временным
сбоем; sqlstate 53300/57P01/57P02/57P03 — тоже; тесты: 256 символов имени/email отклоняются,
заголовок `Allow` у 405, повторная блокировка не теряет несохранённый резерв (autoflush);
опечатка. Вне скоупа, вынесено пользователю: в БД нет `UNIQUE (order_id, product_id)` у строк
заказа — правило «один товар — одной строкой» держат только DTO и `*Body`.

**Тесты перестроены по образцу hex_arch (2026-10-10, по просьбе пользователя):** раскладка
`tests/orders_service/{unit,integration}` зеркалит слои пакета (`unit/application/services`,
`unit/adapters/api/v1`, `integration/adapters/api/controllers`,
`integration/adapters/database/{conftest.py,test_data.py,repositories/,test_unit_of_work.py}`);
секции SETUP/TESTS, фикстуры с явным scope в модулях, классы по методам, имена
`test__<метод>`/`test__<ошибка>`, `# Setup / # Call / # Assert`, `test_data.py` с `*_DATA` и
`insert_*`, `fill_db` autouse и откат сессии после теста. Аннотации типов сохранены
(ruff `ANN`, mypy strict). Итог: 150 тестов, ruff и mypy чисты. Раздел 10 и дерево §3 —
история; действующее описание — README «Тесты».

---

## 16. Докстринги в стиле Google и чистка комментариев (2026-10-10)

**Задача пользователя:** убрать комментарии из кода методов, все пояснения в классах и методах
перестроить в докстринги Google-стиля со смысловым описанием входа, выхода и ошибок.

**Инвентаризация (AST + tokenize по `orders_service/`):** 119 классов и функций без
докстрингов, 32 комментария внутри методов, 9 комментариев в телах классов, 24 комментария
уровня модуля.

**Правила:**
1. Формат — Google, на русском: резюме одним предложением с точкой, при необходимости абзац
   пояснения, затем секции `Args:`, `Returns:` / `Yields:`, `Raises:` (а у классов данных —
   `Attributes:`). Типы не дублируются — они в аннотациях; описывается смысл.
2. `Raises:` перечисляет ошибки ядра (`errors.*`), которые метод поднимает сам или пропускает
   из портов; у транзакционных методов сервисов — и `StorageUnavailable` (его поднимает UoW).
   Инфраструктурные исключения, уходящие как есть, называются одной фразой.
3. Комментарии внутри методов убираются: знание переносится в докстринг (абзац пояснения),
   дублирующее код — удаляется. Комментарии в телах классов (у полей, разделители) — в
   докстринг класса (`Attributes:`), разделители удаляются.
4. Докстринг получают все классы и функции, включая приватные хелперы, свойства, `__init__`,
   `__aenter__`/`__aexit__`, вложенные обработчики, модели Pydantic и dataclass-сущности,
   неймспейсы composition root и функции миграций.
5. Комментарии уровня модуля (константы, разделы) — вне формулировки задачи, остаются;
   исключение — те, что по смыслу относятся к классу или модулю целиком, переносятся
   в докстринг.
6. Тесты не трогаются: их стиль только что выровнен по hex_arch (`# Setup / # Call / # Assert`).
7. Закрепление: в ruff включается `pydocstyle` (`D`, `convention = "google"`) для пакета
   (для `tests/` — выключен), так что отсутствие докстринга или описания аргумента ломает
   `ruff check`.

**Проверка готовности:** AST-скрипт показывает 0 комментариев внутри функций и классов и
0 классов/функций без докстринга; `ruff check` (с `D`), `ruff format --check`, `mypy`,
`pytest` — зелёные.

**Выполнено (2026-10-10).** Пройдены все 56 модулей пакета: 188 классов и функций с
докстрингами, 0 комментариев внутри функций и классов, 16 комментариев уровня модуля
(константы и разделы — по п. 5). В ruff включён `D` (`convention = "google"`, для `tests/`
выключен); шаблон `script.py.mako` даёт докстринги `upgrade`/`downgrade` новым миграциям.
По ходу: D205 на `repositories/base.py` (резюме класса — одной строкой); вложенной `wrapper`
в `transactional.py` добавлены `Args`/`Returns` по замечанию AST-скрипта. Проверка:
`ruff check` / `ruff format --check` / `mypy` / `pytest` (150) — зелёные. Поведение кода
не менялось: дифф — только докстринги и комментарии.

---

## 17. Деплой по образцу hex_arch/deployment (2026-10-10)

**Задача пользователя:** убрать docker-compose из корня и настроить деплой так, как он
настроен в `hex_arch/deployment/`.

**Сделано** — всё в `deployment/` (плоско, без `backend/`: компонент один; раздел 3 плана
в части «compose в корне» этим пересмотрен):

- `Dockerfile` — стадии образца `base → dependency-installer → builder → tests / development /
  production` на uv вместо Poetry. `builder` ставит проект как wheel
  (`uv sync --no-editable`; для этого в `pyproject.toml` добавлен `[build-system]` на
  hatchling), `tests` ставит dev-группу и гоняет unit-тесты при сборке, `development` =
  `tests` + `test_data.py`, `production` копирует из `builder` только `.venv` (без uv,
  исходников и тестов), non-root. Контекст сборки — корень, `.dockerignore` — allow-list.
- `docker-compose.dev.yml` / `docker-compose.prod.yml`: `api`, `db`, `db_for_tests`,
  `api_for_tests` (стадия `tests`, `entrypoint_tests.sh`: в dev падение тестов не роняет
  стенд, в prod `api` ждёт `service_completed_successfully`), `pgadmin`, `nginx`
  (`nginx_config/default.{dev,prod}.conf`; prod закрывает `/docs`, `/redoc`, `/openapi.json`).
  В prod наружу только nginx. Имя проекта задаёт `name:` в compose-файле.
- `entrypoints/`: `entrypoint_alembic.sh` (ждёт БД по `/dev/tcp`, `upgrade head`),
  `entrypoint_api.sh` (миграции → в dev `test_data.py` при `INSERT_PREPARED_DATA=TRUE` →
  `exec uvicorn` с `API_WORKER_COUNT`, `LOG_LEVEL`, `ADDITIONAL_API_ARGS`),
  `entrypoint_tests.sh`.
- `manage/{start,stop,restart,remove}.sh` с флагом `--dev` и `manage/README.md`; скрипты
  экспортируют корневой `.env` перед вызовом compose и работают из любого каталога.
- `test_data.py` — подготовленные данные dev-стенда, идемпотентно; проверяется ruff и mypy
  наравне с пакетом.
- `.env.example`: `TEST_POSTGRES_*` (отдельный Postgres тестов, как `TEST_DATABASE_*` в
  образце) вместо `TEST_DATABASE_URL`; добавлены `API_WORKER_COUNT`, `ADDITIONAL_API_ARGS`,
  `INSERT_PREPARED_DATA`, `PGADMIN_*`, `NGINX_EXTERNAL_PORT`. Conftest БД-тестов:
  `DatabaseTestSettings(database.Settings)` с `env_prefix="TEST_"` — те же поля и
  `database_url`, что у адаптера. В `pyproject.toml` — `testpaths = ["tests"]`, чтобы pytest
  не собирал `deployment/test_data.py`.
- Удалены корневой `docker-compose.yml` и `deployment/postgres/init-test-db.sql`.

**Пересмотренные решения.** Миграции применяет сам API-контейнер в entrypoint, как в
образце; one-shot `migrate` из плана v3 убран (строка про это ушла из таблицы отличий README).

**Сознательные отличия от образца:** в dev `db` и `db_for_tests` публикуются на хост
(`POSTGRES_PORT`, `TEST_POSTGRES_PORT`) ради локальных `uv run uvicorn --reload` и `pytest`;
пароль БД в лог entrypoint не печатается; `exec uvicorn` (сигналы доходят до сервера);
`remove.sh` делает `down --rmi local` вместо списка образов; внутренний порт API и nginx
фиксированы (8000 и 80), чтобы nginx-конфиг не расходился с `.env`.

**Проверка (2026-10-10).** Локально: `uv lock` обновил lock под `[build-system]`; wheel
содержит `alembic/env.py`, `script.py.mako` и `migrations/`; `ruff format --check`,
`ruff check`, `mypy` (89 файлов, включая `deployment/test_data.py`), `pytest` — 150 passed
против `db_for_tests` dev-стенда. Dev-стенд: unit-тесты прошли при сборке стадии `tests`,
`api_for_tests` — 77 passed, exit 0; `api` применил миграцию 0001 и загрузил `test_data.py`
(заказ 1: subtotal 99.98, discount 5.00); API отвечает на :8000 и через nginx :8080, `/docs`
открыт, `/pgadmin4/` → 302. Production (`manage/start.sh`): `api` стартовал после
`api_for_tests` (77 passed), снаружи только nginx (:8000 не слушает), `/docs`, `/redoc`,
`/openapi.json` → 403, `/pgadmin4/` → 302; в образе только `/app/.venv` с установленным
пакетом, пользователь `app`, uv отсутствует. `manage/stop.sh --dev` и `manage/remove.sh`
отработали (контейнеры, образы и сеть prod удалены).

**Дополнение (2026-10-10, позже).** Пользователь разложил `deployment/` на `dockerfiles/Dockerfile` и
`docker-composes/{dev,prod}/docker-compose.*.yml`; ссылки обновлены: `context: ../../..`,
`dockerfile: deployment/dockerfiles/Dockerfile`, `env_file: ../../../.env`, nginx-конфиг `../../nginx_config/`,
пути compose-файлов в `manage/*.sh` и README. Подготовленные данные (`test_data.py`,
`INSERT_PREPARED_DATA`) убраны по решению пользователя: стадия `development` — образ `tests` без
добавлений, `entrypoint_api.sh` — миграции и uvicorn.

---

## 18. Адаптер логирования: анализ образца и план (2026-10-10)

> Разделы 18.3–18.7 — версия до ревью. Итоги ревью — 18.8, действующая версия плана — 18.9.

**Задача пользователя:** добавить адаптер логирования; образец — `hex_arch/adapters/log`, но
сначала проанализировать его на соответствие практике, SOLID и GoF; план прогнать через два
независимых ревью по чистоте архитектуры.

### 18.1 Как сделано в hex_arch

- `adapters/log/settings.py`: `Settings(BaseSettings)` с `LOGGING_LEVEL`, `LOGGING_JSON` и
  свойством `LOGGING_CONFIG`, строящим полный dictConfig: форматтеры `default`/`json`
  (`pythonjsonlogger`), один хендлер `default` → stdout, корневой логгер `""` с этим хендлером,
  `disable_existing_loggers: True`.
- `adapters/log/config.py`: `configure(*configs)` берёт `Settings().LOGGING_CONFIG`, сливает в него
  `formatters`/`handlers`/`loggers` из переданных фрагментов через `dict.update` и вызывает
  `logging.config.dictConfig`.
- `Settings` каждого адаптера имеет своё свойство `LOGGING_CONFIG` с логгерами сторонних библиотек
  этого адаптера (`alembic` и `sqlalchemy` при `SA_LOGS` — у database, `gunicorn`/`spectree` — у
  API, `kombu` — у message_bus), все с `handlers: ["default"]`, `propagate: False` и уровнем из
  собственного `LOGGING_LEVEL`.
- Launcher: класс-неймспейс `Logger` вызывает `log.configure(Settings.db.LOGGING_CONFIG,
  Settings.api.LOGGING_CONFIG, …)` — состав фрагментов повторяется в каждом launcher-модуле.
- Логгеры в коде: `logging.getLogger(constants.LOGGER_PREFIX)`,
  `logging.getLogger(self.__class__.__name__)`; слой `application` не логирует вовсе.

### 18.2 Анализ

**Что верно и берём:**

- (G1) Логирование — инфраструктурная, сквозная забота: конфигурация живёт в адаптере и
  применяется в composition root, ядро не знает о хендлерах и форматах (направление
  зависимостей внутрь — D из SOLID).
- (G2) Один хендлер в stdout и JSON-вариант для production — 12-factor, контейнеры собирают
  stdout.
- (G3) Знание о логгерах сторонних библиотек остаётся у адаптера, который эти библиотеки
  использует (`kombu` → message_bus, `alembic` → database): новый адаптер приносит своих
  логгеров без правки `log` (OCP, SRP). Идея верная, реализация — нет (B1, B3).

**Что не так:**

- (B1) Скрытая связность по магической строке: фрагменты всех адаптеров ссылаются на хендлер
  `default`, объявленный внутри `log.Settings`. Переименование хендлера ломает каждый адаптер;
  адаптеры зависят от детали реализации соседнего адаптера (нарушение DIP/OCP). Связка при этом
  не нужна: логгеру достаточно `propagate` к корню.
- (B2) `disable_existing_loggers: True` при `dictConfig` после импортов: логгеры, созданные на
  уровне модулей до `configure` (`logging.getLogger(__name__)`), молча отключаются. В hex_arch
  это не стреляет лишь потому, что логгеры берутся в `__init__` экземпляров; у нас
  `error_handlers.logger` и `lifespan.logger` модульные — замолчали бы.
- (B3) `Settings` как строитель: pydantic-настройки (значения из окружения) смешаны с
  построением dictConfig (свойства `LOGGING_CONFIG` в четырёх классах Settings) — SRP. Плюс
  `LOGGING_LEVEL` читается тремя разными Settings — дублирование одной переменной.
- (B4) `configure()` сам создаёт `Settings()` вместо получения из composition root — скрытая
  зависимость, не подменить в тесте, непоследовательно с остальными адаптерами (DIP).
- (B5) Слияние фрагментов — неглубокий `dict.update`: порядок аргументов решает молча (последний
  одноимённый логгер перетирает предыдущий), конфликтов никто не видит.
- (B6) Имена логгеров `LOGGER_PREFIX` и `self.__class__.__name__` теряют иерархию модулей:
  уровень не настроить по пакету, одноимённые классы разных пакетов сливаются. Практика —
  `logging.getLogger(__name__)`.
- (B7) `propagate: False` у корневого логгера бессмысленен; `SA_LOGS` включает логгер `sqlalchemy`
  целиком (`pool`, `orm`, `dialects`) вместо `sqlalchemy.engine`.
- (B8) Нет контекста запроса: записи разных HTTP-запросов неразличимы; access-лог сервера лишь
  перенаправлен в общий хендлер.
- (B9) «Адаптер» без порта: `adapters/log` ничего не приспосабливает к интерфейсу ядра — это
  конфигурация инфраструктуры. Само по себе это нормально (логирование — сквозная
  функциональность, а `logging` — готовый фасад с подключаемыми обработчиками), но называть его
  паттерном Adapter нельзя; у нас это будет сказано явно.

**GoF внутри `logging` (чтобы в README не натягивать):** иерархия логгеров с `propagate` и
фильтры — Chain of Responsibility; хендлеры — Observer; `Formatter` — Strategy; dictConfig —
декларативный Builder. В нашем адаптере явно называются три: Builder — чистая функция
`build_config`, Strategy — выбор форматтера по `LOG_FORMAT`, Chain of Responsibility —
`RequestIdFilter`.

### 18.3 Решения (зафиксированы пользователем / приняты в плане)

- **D1.** Логирование — сквозная функциональность: во всех слоях, включая ядро,
  `logger = logging.getLogger(__name__)`. Порт `interfaces.Logger` не вводится (YAGNI: stdlib —
  стабильный фасад, подмена в тестах — `caplog`). Ядро не знает о хендлерах, форматах, уровнях.
- **D2.** `adapters/log/` — адаптер конфигурации (имя как в hex_arch, в README помечен как
  «конфигурация инфраструктуры, не паттерн Adapter»): `settings.py` — только значения
  (`LOG_LEVEL`, `LOG_FORMAT`), `config.py` — `build_config(settings, levels)` (чистый строитель
  dictConfig, тестируется без побочных эффектов) и `configure(settings, *, levels, filters)`
  (применяет `dictConfig`, навешивает фильтры на корневые хендлеры).
- **D3.** Контракт между адаптерами — `Mapping[str, str]` «имя логгера → уровень», без имён
  хендлеров: `database.logger_levels(settings)` и `api.logger_levels()`. Каждый такой логгер
  настраивается как `{"level": …, "handlers": [], "propagate": True}`: уровень задан, свои хендлеры
  сняты (так `uvicorn.*` перестают писать своим форматом), записи идут в корневой хендлер.
  Слияние двух мапингов делает composition root (`{**a, **b}`) — конфликты имён исключены
  составом: database знает `sqlalchemy.*`/`alembic`, api — `uvicorn.*`.
- **D4.** `disable_existing_loggers=False`.
- **D5.** `LOG_LEVEL` переезжает из `launchers/config.py` в `adapters/log/settings.py`;
  `config.Settings` остаётся с `DISCOUNT_*`. Новая `LOG_FORMAT: Literal["text", "json"] = "text"`.
- **D6.** SQL-лог — уровнем логгера `sqlalchemy.engine` (INFO при `POSTGRES_ECHO_SQL`, иначе
  WARNING), а не `echo=True` у движка: `echo` вешает на логгер собственный `StreamHandler`, и при
  настроенном корне каждая строка SQL пишется дважды. Имя переменной остаётся.
- **D7.** Корреляция запросов целиком в API-адаптере (`adapters/api/request_id.py`): contextvar
  `request_id`, чистый ASGI-middleware `RequestIdMiddleware` (берёт `X-Request-ID` из запроса или
  генерирует uuid4, ставит contextvar на время запроса, возвращает заголовок в ответе) и
  `RequestIdFilter(logging.Filter)`, дописывающий `record.request_id`. Log-адаптер о запросах не
  знает: фильтры приходят в `configure(filters=…)` из composition root (OCP). Текстовый
  форматтер печатает `%(request_id)s` с дефолтом `-` (`logging.Formatter(defaults=…)` через
  фабрику `"()"` в dictConfig), JSON-форматтер добавляет нестандартные атрибуты записи сам.
  Ожидается, что и `uvicorn.access` получит `request_id`: uvicorn пишет access-лог из `send()`,
  вызываемого внутри задачи приложения, где contextvar уже установлен; проверяется на стенде.
- **D8.** JSON — `python-json-logger` (как в hex_arch), без самописного форматтера.
- **D9.** Логи ядра: INFO в сервисах на успешную смену состояния — `Order.place/pay/cancel`,
  `Customer.add`, `Product.add` (идентификаторы и сумма/статус). Ожидаемые доменные ошибки не
  логируются (их переводит обработчик ошибок; 5xx он же логирует). Сущности и `@transactional`
  не логируют: сущности — чистый домен, обёртка — шум на каждый вызов.
- **D10.** uvicorn запускается CLI с `--log-level` как сейчас; после импорта приложения наш
  `dictConfig` перехватывает `uvicorn`, `uvicorn.error`, `uvicorn.access` (D3), поэтому в
  воркерах формат единый; две-три строки master-процесса остаются в формате uvicorn — допустимо,
  фиксируется в README. Генерация `--log-config` для uvicorn из того же `build_config` отклонена:
  второй источник правды в деплое.
- **D11.** Сообщения логов — на русском, как ошибки и документация проекта.

### 18.4 Структура

```
orders_service/adapters/log/
├── __init__.py        # Settings, build_config, configure; докстринг: конфигурация, не порт
├── settings.py        # Settings(BaseSettings): LOG_LEVEL="INFO", LOG_FORMAT="text"|"json"
└── config.py          # build_config(settings, levels) -> dict[str, Any]; configure(settings, *, levels=None, filters=())
orders_service/adapters/database/logs.py   # logger_levels(settings) -> dict[str, str]: sqlalchemy.engine, alembic
orders_service/adapters/api/logs.py        # logger_levels() -> dict[str, str]: uvicorn, uvicorn.error, uvicorn.access
orders_service/adapters/api/request_id.py  # request_id: ContextVar[str | None], REQUEST_ID_HEADER, RequestIdMiddleware, RequestIdFilter
```

`build_config` (суть):

```python
{
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "text": {
            "()": "logging.Formatter",
            "fmt": "%(asctime)s %(levelname)-8s [%(name)s] [%(request_id)s] %(message)s",
            "defaults": {"request_id": "-"},
        },
        "json": {
            "()": "pythonjsonlogger.json.JsonFormatter",
            "fmt": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": settings.LOG_FORMAT,
        }
    },
    "root": {"level": settings.LOG_LEVEL.upper(), "handlers": ["stdout"]},
    "loggers": {
        name: {"level": level, "handlers": [], "propagate": True} for name, level in levels.items()
    },
}
```

Composition root (`launchers/api.py`):

```python
class Settings:
    db = database.Settings()
    service = config.Settings()
    log = log.Settings()


class Logger:
    log.configure(
        Settings.log,
        levels={**database.logger_levels(Settings.db), **api.logger_levels()},
        filters=[api.RequestIdFilter()],
    )
```

`alembic_runner.run_cmd`: `log.configure(log.Settings(), levels=database.logger_levels(db_settings))`
с одним экземпляром `database.Settings()` на `make_config` и `logger_levels`.

### 18.5 Шаги

1. Зависимость `python-json-logger` (uv add); пакет `adapters/log` (D2, D4, D5); unit-тесты
   `build_config`.
2. `launchers/config.py` без `LOG_LEVEL`; `launchers/api.py` и `alembic_runner.py` — `configure`
   вместо `basicConfig` (см. 18.4).
3. database: `logs.py` с `logger_levels`, `Database.__init__` без `echo` (D6), экспорт из пакета;
   unit-тест маппинга по `POSTGRES_ECHO_SQL`.
4. api: `logs.py`, `request_id.py` (D7), `create_app` добавляет `RequestIdMiddleware`
   (`app.add_middleware`), экспорт `logger_levels` и `RequestIdFilter`; unit-тесты фильтра и
   middleware, HTTP-тест заголовка `X-Request-ID` (возврат переданного, генерация uuid4).
5. Ядро: `logger` в `services/{order,customer,product}.py`, INFO по D9. Тестов на текст
   сообщений нет (хрупко; `caplog` не проверяет поведение).
6. Конфигурация и документация: `.env.example`/`.env` — `LOG_FORMAT=text` с пометкой «в
   production — json»; `entrypoint_api.sh` без изменений; README — раздел «Логирование»
   (где настраивается, контракт `logger_levels`, request id, `LOG_FORMAT`, почему нет порта,
   строки master-процесса uvicorn), таблица паттернов (+ Builder `build_config`, Strategy
   форматтер, Chain of Responsibility `RequestIdFilter`), таблица отличий от hex_arch (строка про
   фрагменты `LOGGING_CONFIG` → `logger_levels`); CLAUDE.md — архитектура и запрет `echo`;
   `docs/plan.md` — итоги.
7. Проверки: ruff / mypy / pytest; на dev-стенде: `LOG_FORMAT=json` → JSON-строки с
   `request_id`; запрос с `X-Request-ID` и без → заголовок в ответе, тот же id в записях
   сервиса и `uvicorn.access`; `POSTGRES_ECHO_SQL=true` → каждый SQL один раз.

### 18.6 Тест-план

| Модуль | Кейсы |
|---|---|
| `unit/adapters/log/test_config.py` — `TestBuildConfig` | `test__text_formatter_by_default`, `test__json_formatter`, `test__root_level_uppercased`, `test__levels_become_propagating_loggers` (handlers `[]`, propagate `True`), `test__existing_loggers_not_disabled` |
| `unit/adapters/api/test_request_id.py` — `TestRequestIdFilter`, `TestRequestIdMiddleware` | фильтр: `request_id` из contextvar / `-` без него; middleware: генерирует uuid4 без заголовка, пропускает переданный, contextvar установлен на время вызова приложения и сброшен после, заголовок в ответе (dummy ASGI-приложение, без FastAPI) |
| `integration/adapters/api/controllers/test_request_id.py` — `TestRequestId` | `test__header_echoed`, `test__header_generated` через `client` |
| `unit/adapters/database/test_logs.py` — `TestLoggerLevels` | параметризация `POSTGRES_ECHO_SQL` → уровень `sqlalchemy.engine` |

`configure()` юнитами не тестируется: тонкая обёртка над `dictConfig`, а её вызов меняет глобальное
состояние `logging` в процессе pytest (ломает `caplog`); проверяется на стенде (шаг 7).

### 18.7 Сомнения для ревью

1. Контракт `logger_levels() -> Mapping[str, str]` против фрагментов dictConfig (hex_arch) и
   против «log-адаптер сам знает uvicorn/sqlalchemy/alembic» — не перебор ли ради OCP для трёх
   адаптеров?
2. `configure(..., filters=…)` с программным `handler.addFilter` после `dictConfig` — чисто ли,
   или фильтр должен быть описан в самом dictConfig (`filters` с `"()"`)?
3. `RequestIdFilter` живёт в API-адаптере и экспортируется наружу как `logging.Filter` — не
   странно ли для HTTP-адаптера; альтернатива — contextvar и фильтр в `adapters/log`, тогда
   API-адаптер импортирует `log` (зависимость адаптер → адаптер).
4. Логи в сервисах ядра (D9): уровень INFO и состав полей; не логировать ли в `@transactional`.
5. Не слишком ли много для учебного минимума: JSON, request id, логи ядра — что выкинуть.
6. Перенос `LOG_LEVEL` в `adapters/log.Settings` и судьба `POSTGRES_ECHO_SQL` (имя оставить?).
7. Дыры тест-плана: что холостое, чего не хватает.

### 18.8 Итоги ревью плана (2026-10-10)

Два независимых рецензента, оба — чистота архитектуры, разный фокус: A — границы слоёв,
направление зависимостей, обоснованность SOLID/GoF-выводов; B — дизайн модулей, контракты,
конфигурация, YAGNI, тест-план. BLOCKER нет. Три MAJOR найдены обоими независимо (сильный
сигнал); расхождение одно — место фильтра request-id. Ключевые утверждения перепроверены
скриптом (`scratchpad/verify_review_claims.py`): `add_middleware` → 500 без заголовка и id в
обработчике; `build_middleware_stack` → заголовок и id есть; `dictConfig` принимает класс
фильтра через `"()"`, фильтр на хендлере обогащает пропагированные записи.

| # | Находка | Решение |
|---|---|---|
| 1 | **[MAJOR, A+B]** `app.add_middleware` ставит `RequestIdMiddleware` внутрь `ServerErrorMiddleware`: ответ 500 уходит без `X-Request-ID`, обработчик 500 и `uvicorn.access` не видят id | **Принято.** Middleware оборачивает весь стек: подкласс FastAPI переопределяет `build_middleware_stack`; класс переименован `FastApiWithout422` → `App` (два отличия от FastAPI в одном докстринге). Трассировка uvicorn «Exception in ASGI application» пишется уже после выхода из приложения и остаётся без id — принято как ограничение, в README; строка `uvicorn.access` со статусом 500 и id идёт рядом. Вариант A «не сбрасывать contextvar при исключении» отклонён: несимметричный сброс, опирается на то, что сервер даёт каждому запросу свой контекст |
| 2 | **[MAJOR, B]** Чистый ASGI-middleware получает и `lifespan`: чтение заголовков из такого scope — `KeyError` на старте | **Принято.** `scope["type"] != "http"` → пропустить без изменений; тест |
| 3 | **[MAJOR, A+B]** D9: INFO «заказ оформлен» пишется в сервисе до `commit()` обёртки и врёт при сбое фиксации (`StorageUnavailable`) | **Принято.** Сервисы не логируют (D1 остаётся правилом, README объясняет: сервис не знает об исходе фиксации — это и есть учебный тезис). Точка правды — DEBUG в `@transactional` после `commit()`: `"%s: транзакция зафиксирована", method.__qualname__` |
| 4 | **[MAJOR, A+B]** `adapters/api/logs.py` с именами `uvicorn.*` — знание о сервере протекло в FastAPI-адаптер, который uvicorn не импортирует (сервер выбирают launcher и entrypoint) | **Принято.** Модуль и `api.logger_levels()` убраны; имена — константа `UVICORN_LOGGERS` в `launchers/api.py` с уровнем `NOTSET` (наследуют `LOG_LEVEL`); `alembic` не настраивается (без `fileConfig` идёт в корень); `database.logger_levels(settings)` → только `sqlalchemy.engine`, живёт в `database.py` рядом с `Database`. Контракт `logger_levels` остаётся с одним поставщиком — это уже не «общий контракт», а функция адаптера БД |
| 5 | **[MAJOR, B] против «проверено» A:** фильтр и contextvar в API-адаптере + формат `%(request_id)s` в log-адаптере — связность по магическому имени (та же B1); A: вариант плана чище, т.к. не создаёт первой зависимости адаптер → адаптер | **Принято решение B.** `request_id` (contextvar) и `RequestIdFilter` — в `adapters/log/context.py`, фильтр объявлен в dictConfig; `configure(filters=…)`, `addFilter` и `defaults` убраны; `RequestIdMiddleware` импортирует `log.request_id` явно. Правило: `adapters/log` — инфраструктурная утилита без порта (D2), адаптеры используют её как библиотеку; обратная зависимость (`log` → `api`/`database`) запрещена; между адаптерами портов (`api` ↔ `database`) импортов нет. **Возражение A вынесено пользователю** как альтернатива (фильтр в `api`, формат log-адаптера знает поле по имени) |
| 6 | **[MINOR, A]** источник уровня перехваченных логгеров не определён; `--log-level` entrypoint перекрывается нашим dictConfig | **Принято.** `NOTSET` для `uvicorn.*` (см. 4): `LOG_LEVEL=WARNING` глушит access-лог, `DEBUG` включает debug uvicorn; `--log-level` в entrypoint влияет только на master-процесс — в README |
| 7 | **[MINOR, A+B]** фабрика `"()"` для `defaults` и программный `addFilter` не нужны (3.12 принимает `defaults` в dictConfig; фильтр описывается в dictConfig) | **Принято** (см. 5); форматтеры через `class`, `datefmt` явно; строится только выбранный форматтер под именем `default` (B) |
| 8 | **[MINOR, A+B]** B5 упрекает образец в молчаливом слиянии, а D3 сливает `{**a, **b}` так же | **Принято частично.** B5 переформулирован: не дефект сам по себе, риск при четырёх источниках с разными дефолтами. У нас два источника с заведомо разными именами, слияние в composition root; проверка пересечения не добавляется (YAGNI) |
| 9 | **[MINOR, A+B]** GoF-маркировки натянуты: функция с литералом словаря — не Builder, выбор имени форматтера — не Strategy, фильтр, всегда возвращающий `True`, — не CoR | **Принято.** В таблицу паттернов README ничего не добавляется; одна фраза в разделе «Логирование»: `logging` сам построен на Observer/Strategy/Chain of Responsibility, адаптер их только конфигурирует. `build_config` → `make_config` (единый глагол с `alembic_runner.make_config`) |
| 10 | **[MINOR, A+B]** `LOG_LEVEL: str` без валидации: `VERBOSE`/`TRACE` валят процесс внутри `dictConfig` | **Принято.** `Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]` + `field_validator(mode="before")` с `.upper()` — ошибка конфигурации на старте, как у остальных Settings |
| 11 | **[MINOR, A+B]** `X-Request-ID` клиента без ограничений попадает в лог и ответ | **Принято.** Принимается только `^[A-Za-z0-9._-]{1,64}$`, иначе генерируется uuid4; тест |
| 12 | **[MINOR, B]** JSON-форматтер — самая низкая учебная ценность, выкинуть | **Отклонено**, вынесено пользователю: паритет с hex_arch (`LOGGING_JSON`), стандарт для контейнеров; после п. 7 цена — одна ветка `if` и зависимость `python-json-logger` |
| 13 | **[MINOR, A+B]** тест-план: четыре структурных теста холостые; нет кейсов на 500, на сброс contextvar при исключении, на passthrough `lifespan`, на валидность uuid4; `configure` можно проверить в subprocess | **Принято.** Структурных тестов два (`levels` → `loggers`; выбор форматтера); поведение `configure` — smoke-тест в subprocess; middleware и HTTP-кейсы — см. 18.9 |
| 14 | **[NIT, A+B]** имена и забытые правки: `request_id.py` против переменной `request_id`; `logs.py` читается как «логи»; `Settings.log = log.Settings()` затеняет модуль; CLAUDE.md относит `LOG_LEVEL` к `launchers/config.py`; строки плана 681 и 930 противоречат разделу 18; README без `log` в диаграмме и таблице слоёв; `__init__.py` новых тестовых пакетов; `uv.lock` | **Принято.** Contextvar уезжает в `log.context` (конфликт имён исчезает); `logs.py` нет; `Settings.logging = log.Settings()`; остальное — в шаг 6; строки 681/930 помечены как пересмотренные |
| 15 | **[NIT, A]** уточнения к 18.2: B2 — при `disable_existing_loggers: True` глушатся и сторонние логгеры, созданные при импорте (`sqlalchemy.engine.Engine` при `SA_LOGS=false` — навсегда); B3 — четыре Settings с `LOGGING_LEVEL` и разными дефолтами (`med_sharing_api` — `DEBUG`); B7 — `pool`/`orm` ощутимы только на DEBUG | **Принято** как уточнения анализа (здесь, без правки 18.2) |
| 16 | **[MINOR, A, вне скоупа]** 503 пишется без причины: `handle_app_error` логирует `exc.message`, `__cause__` (SQLSTATE/текст asyncpg) не попадает в лог нигде | **Вопрос пользователю:** починить сейчас (одна строка: `__cause__` в сообщение, без трассировки; тест `exc_info is None` остаётся) / в техдолг / не трогать. Рекомендация — починить в рамках этой задачи |

### 18.9 План v2 — действующий (после ревью)

**Решения:**

- **D1** (без изменений): stdlib `logging.getLogger(__name__)` в любом слое, порта нет.
- **D2'**: `adapters/log` — инфраструктурная утилита без порта: `settings.py` (значения),
  `config.py` (`make_config`, `configure`), `context.py` (`request_id`, `RequestIdFilter`).
  Адаптеры могут импортировать `log` как библиотеку; `log` не импортирует адаптеры; между
  `api` и `database` импортов нет.
- **D3'**: уровни логгеров сторонних библиотек: `database.logger_levels(settings)` →
  `{"sqlalchemy.engine": "INFO" | "WARNING"}`; имена uvicorn — `UVICORN_LOGGERS` в
  `launchers/api.py` с `NOTSET`; слияние — в composition root. Каждый такой логгер в dictConfig:
  `{"level": …, "handlers": [], "propagate": True}`.
- **D4**: `disable_existing_loggers=False`. **D6**: без `echo` у движка. **D8**: JSON через
  `python-json-logger` (на решение пользователя). **D10**: uvicorn CLI с `--log-level` (влияет
  только на master-процесс). **D11**: сообщения на русском.
- **D5'**: `LOG_LEVEL: Literal[...]` с валидатором регистра и `LOG_FORMAT: Literal["text", "json"]`
  в `log.Settings`; `launchers/config.py` остаётся с `DISCOUNT_*`.
- **D7'**: contextvar и фильтр — в `log.context`; `RequestIdMiddleware` — в
  `adapters/api/request_id.py`, стоит снаружи всего стека (`App.build_middleware_stack`),
  пропускает не-HTTP scope, принимает `X-Request-ID` по регулярному выражению или генерирует
  uuid4, возвращает заголовок, всегда сбрасывает contextvar в `finally`. Ограничение:
  трассировка uvicorn для 500 без id (строка `uvicorn.access` с id рядом).
- **D9'**: сервисы не логируют; `@transactional` пишет DEBUG после `commit()`.

**Структура:**

```
orders_service/adapters/log/
├── __init__.py      # Settings, make_config, configure, request_id, RequestIdFilter
├── settings.py      # LOG_LEVEL (Literal + upper), LOG_FORMAT
├── config.py        # make_config(settings, levels) -> dict[str, Any]; configure(settings, *, levels) -> None
└── context.py       # request_id: ContextVar[str | None]; RequestIdFilter: record.request_id = значение или "-"
orders_service/adapters/api/request_id.py      # REQUEST_ID_HEADER, регулярное выражение, RequestIdMiddleware (ставит log.request_id)
orders_service/adapters/api/app.py             # App(FastAPI): openapi() без 422, build_middleware_stack() с RequestIdMiddleware снаружи
orders_service/adapters/database/database.py   # + logger_levels(settings)
orders_service/launchers/api.py                # UVICORN_LOGGERS; Settings.logging; Logger: log.configure(...)
orders_service/application/transactional.py    # DEBUG после commit
```

`make_config` (суть):

```python
def make_config(settings: Settings, levels: Mapping[str, str]) -> dict[str, Any]:
    formatter: dict[str, Any] = (
        {
            "class": "pythonjsonlogger.json.JsonFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        }
        if settings.LOG_FORMAT == "json"
        else {"format": "%(asctime)s %(levelname)-8s [%(name)s] [%(request_id)s] %(message)s"}
    )
    formatter["datefmt"] = "%Y-%m-%d %H:%M:%S"
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"request_id": {"()": RequestIdFilter}},
        "formatters": {"default": formatter},
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "default",
                "filters": ["request_id"],
            }
        },
        "root": {"level": settings.LOG_LEVEL, "handlers": ["stdout"]},
        "loggers": {
            name: {"level": level, "handlers": [], "propagate": True}
            for name, level in levels.items()
        },
    }
```

JSON-форматтер включает `request_id` автоматически: фильтр кладёт атрибут в каждую запись,
python-json-logger добавляет нестандартные атрибуты записи в JSON.

Composition root:

```python
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


class Settings:
    db = database.Settings()
    service = config.Settings()
    logging = log.Settings()


class Logger:
    log.configure(
        Settings.logging,
        levels={**database.logger_levels(Settings.db), **dict.fromkeys(UVICORN_LOGGERS, "NOTSET")},
    )
```

`alembic_runner.run_cmd`: `log.configure(log.Settings(), levels=database.logger_levels(db_settings))`.

**Шаги:**

1. `uv add python-json-logger` (обновляет `uv.lock`); пакет `adapters/log` (settings, config,
   context, `__init__`); тесты: `tests/orders_service/unit/adapters/log/` (`__init__`,
   `test_settings`, `test_config`, `test_context`), `tests/orders_service/integration/adapters/log/`
   (`__init__`, `test_configure` — subprocess).
2. launchers: `config.py` без `LOG_LEVEL`; `api.py` — `UVICORN_LOGGERS`, `Settings.logging`,
   `Logger` через `configure`; `alembic_runner.py` — `configure` вместо `basicConfig`.
3. database: `logger_levels` в `database.py`, `Database.__init__` без `echo`, экспорт из
   пакета; тест `tests/orders_service/unit/adapters/database/test_database.py`.
4. api: `request_id.py`; `app.py` — `App` с `build_middleware_stack`; тесты: unit
   `tests/orders_service/unit/adapters/api/test_request_id.py`, HTTP
   `tests/orders_service/integration/adapters/api/controllers/test_request_id.py`.
5. Ядро: DEBUG в `@transactional` после commit; тест в `test_transactional.py` (`caplog`,
   уровень и логгер, без привязки к полному тексту).
6. Конфигурация и документация: `.env.example`/`.env` — блок «Логирование
   (adapters/log/settings.py)»: `LOG_LEVEL`, `LOG_FORMAT=text` (prod — json); CLAUDE.md —
   настройки, правило импорта `adapters/log`, запрет `echo`, ограничение трассировки 500;
   README — раздел «Логирование», диаграмма и таблица слоёв с `log`, `FastApiWithout422` → `App`,
   таблица отличий от hex_arch (фрагменты `LOGGING_CONFIG` → `logger_levels` + константа
   launcher), фраза о паттернах внутри `logging`; строки плана 681/930 помечены; итоги в
   `docs/plan.md`.
7. Проверки: ruff / mypy / pytest; dev-стенд: `LOG_FORMAT=json` → JSON с `request_id` в записях
   `uvicorn.access`; запрос с валидным, невалидным и без `X-Request-ID`; `POSTGRES_ECHO_SQL=true`
   → каждый SQL один раз; `LOG_LEVEL=WARNING` → access-лог молчит; `LOG_LEVEL=DEBUG` → строка
   «транзакция зафиксирована».

**Тест-план v2:**

| Модуль | Кейсы |
|---|---|
| `unit/adapters/log/test_settings.py` — `TestSettings` | `test__level_uppercased` (`Settings(LOG_LEVEL="debug", _env_file=None)`), `test__unknown_level_rejected` (`TRACE` → `ValidationError`) |
| `unit/adapters/log/test_config.py` — `TestMakeConfig` | `test__levels_become_propagating_loggers` (`handlers: []`, `propagate: True`, уровень как передан), `test__formatter_selected_by_format` (text: формат с `request_id`; json: класс `pythonjsonlogger.json.JsonFormatter`) |
| `unit/adapters/log/test_context.py` — `TestRequestIdFilter` | `test__request_id_from_context`, `test__dash_without_context`, `test__record_passes` |
| `integration/adapters/log/test_configure.py` — `TestConfigure` (subprocess, параметризация `LOG_FORMAT`) | дочерний процесс: `configure`, запись из логгера, созданного до `configure`, запись `uvicorn.access` при установленном `request_id`; текст — regex с `[-]` и с id; json — парсится, содержит `request_id`, `levelname`, `name`, `message` |
| `unit/adapters/api/test_request_id.py` — `TestRequestIdMiddleware` (dummy ASGI, без FastAPI) | `test__generates_uuid4`, `test__accepts_valid_header`, `test__rejects_invalid_header` (параметризация: длина > 64, недопустимые символы → сгенерирован), `test__context_set_during_app_and_reset_after`, `test__context_reset_after_exception`, `test__header_in_response`, `test__non_http_scope_passthrough` |
| `integration/adapters/api/controllers/test_request_id.py` — `TestRequestId` | `test__header_echoed`, `test__header_generated`, `test__header_on_error_responses` (параметризация: 404 неизвестный путь, 503 `StorageUnavailable` из мока сервиса, 500 необработанное исключение с `raise_app_exceptions=False`) |
| `unit/adapters/database/test_database.py` — `TestLoggerLevels` | параметризация `POSTGRES_ECHO_SQL` → `{"sqlalchemy.engine": "INFO" / "WARNING"}` |
| `unit/application/test_transactional.py` — `TestTransactional` | `test__commit_logged_at_debug` (`caplog`, логгер `orders_service.application.transactional`, уровень DEBUG, `__qualname__` метода в сообщении) |

**На решение пользователя:** (1) место фильтра request-id — принят вариант B (в `log`),
альтернатива A — в `api`; (2) оставить ли JSON-форматтер; (3) `__cause__` в WARNING для 503
(п. 16) — сейчас / техдолг / не трогать; (4) ограничение «трассировка 500 без id» принять как
есть или не сбрасывать contextvar на пути исключения (вариант A).

### 18.10 Актуализация под новый Unit of Work (2026-10-10)

После раздела 19 (`@transactional` удалён, UoW создаётся вызываемым объектом и сам управляет
сессией) план 18.9 меняется так:

- **D9''.** DEBUG-запись о фиксации переезжает из обёртки в `database.UnitOfWork.commit()`:
  «транзакция зафиксирована». Об исходе фиксации знает только адаптер БД, а корреляцию с
  запросом даёт `request_id` в записи. Сервисы по-прежнему не логируют.
- **Шаг 5 и тест-план:** вместо `test_transactional.py` — `integration/adapters/database/
  test_unit_of_work.py`, класс `TestCommit`, тест `test__commit_logged_at_debug` (`caplog` на
  логгер `orders_service.adapters.database.unit_of_work`, уровень DEBUG, без привязки к полному
  тексту).
- **Структура 18.9:** строка `orders_service/application/transactional.py # DEBUG после commit`
  → `orders_service/adapters/database/unit_of_work.py # DEBUG в commit()`.
- **Вопросы 18.9 на решение пользователя:** (1) фильтр и contextvar в `adapters/log` — принято;
  (2) JSON-форматтер остаётся; (3) `__cause__` в WARNING для 503 — в эту задачу не входит, ждёт
  решения; (4) трассировка uvicorn для 500 без id — принято как ограничение.
- Остальное (D1–D8, D10, D11, структура, шаги 1–4 и 6–7, тест-план) — без изменений.

### 18.11 Реализация и проверка (2026-10-10)

Реализовано по 18.9 с поправками 18.10. Отличие от плана одно: JSON-форматтер объявлен через
фабрику `"()"` с `json_ensure_ascii=False` — иначе python-json-logger экранирует кириллицу
(`"Тр..."`), и сырой лог нечитаем; на стенде это проявилось как «пропавшая» строка
«Транзакция зафиксирована». Зависимость `python-json-logger>=4.2.0` добавлена в `pyproject.toml`.

**Состав:** `adapters/log/{settings,config,context}.py`; `adapters/api/request_id.py` и `App`
(бывший `FastApiWithout422`) с `build_middleware_stack`; `database.logger_levels` и движок без
`echo`; DEBUG в `UnitOfWork.commit`; `launchers/api.py` (`UVICORN_LOGGERS`, `Settings.logging`,
`Logger` через `configure`), `alembic_runner.py`, `launchers/config.py` без `LOG_LEVEL`;
`.env.example`/`.env` — блок «Логирование»; README (раздел «Логирование», диаграмма, таблицы
слоёв, тестов и отличий), CLAUDE.md.

**Тесты (34 новых, всего 187):** `unit/adapters/log/` (settings, make_config, фильтр),
`integration/adapters/log/test_configure.py` (дочерний процесс: text/json, ранний логгер,
`uvicorn.access` с id, WARNING режет SQL, кириллица не экранирована, ровно две строки),
`unit/adapters/api/test_request_id.py` (ASGI-заглушка), `integration/.../test_request_id.py`
(заголовок на 200/404/503/500), `unit/adapters/database/test_database.py` (`logger_levels`),
`TestCommit` в `test_unit_of_work.py`.

**Стенд (dev, `LOG_FORMAT=json`, `LOG_LEVEL=DEBUG`, `POSTGRES_ECHO_SQL=true`):** `X-Request-ID`
возвращается на 201 напрямую и на 404 через nginx, недопустимое значение заменено uuid4; все
строки одного запроса (SQL, DEBUG о фиксации, `uvicorn.access`) несут один `request_id`;
`INSERT INTO customers` в логе один раз (без дублей от `echo`); миграции Alembic пишут в тот же
JSON; вне JSON — только две строки master-процесса uvicorn. `LOG_LEVEL=WARNING` + `text`:
access-лог и INFO молчат. ruff, mypy, pytest — зелёные; стенд после проверки снесён.

---

## 19. Переделка Unit of Work: без класса-фабрики и без `@transactional` (2026-10-10)

**Задача пользователя:** UoW по-прежнему создаётся на каждый вызов сервиса, но без отдельного
объекта `UnitOfWorkFactory`: сам `UnitOfWork` получает `session_factory`, создаёт сессию и
репозитории; в сервис он передаётся вызываемым объектом (лямбда/`partial`), который сервис
вызывает сам; декоратор `@transactional` убирается — транзакции живут в UoW, сервисы только
вызывают репозитории. План логирования (раздел 18) переделывается после этого.

**Почему это лучше прежнего (итог обсуждения):** лямбда и фабрика — одно и то же, уходят два
класса (порт и реализация фабрики) и весь аппарат декоратора: `Concatenate`-типизация,
протокол `TransactionalService`, параметр `uow`, «который никто не передаёт», правило о
невложенности и тесты обёртки. Граница транзакции становится видимой в теле метода — как в
«Architecture Patterns with Python». Декоратор давал DRY на три строки и гарантию «метод
транзакционен», которая без него не нужна: без `async with` методу неоткуда взять репозитории.

**Решения:**

- **U1.** Порт `interfaces.UnitOfWork` без изменений (свойства-репозитории, `__aenter__` /
  `__aexit__`, `commit`). ABC `UnitOfWorkFactory` заменён типом
  `type UnitOfWorkFactory = Callable[[], UnitOfWork]` — тип вызываемого объекта, класса нет.
- **U2.** `database.UnitOfWork(session_factory)`: `__aenter__` создаёт сессию и три репозитория
  на ней; `__aexit__` — как прежде (откат, закрытие, перевод сбоев в `StorageUnavailable`);
  `commit` — как прежде. Повторный вход в тот же объект открывает новую сессию.
- **U3.** Сервисы: каждый публичный метод открывает `async with self.uow_factory() as uow:`;
  запись заканчивается явным `await uow.commit()`, чтения commit не вызывают; DTO строится
  внутри контекста. `_lock_products(uow, …)` без изменений.
- **U4.** Composition root: `Adapters.uow_factory = functools.partial(database.UnitOfWork,
  db.session_factory)` — то же, что лямбда, но без ruff E731 (присваивание лямбды) и с
  выводимым типом; лямбда в теле класса к тому же не увидела бы `db` (область видимости класса
  недоступна вложенным функциям).
- **U5.** `application/transactional.py` и `tests/.../test_transactional.py` удаляются;
  инвариант «новый UoW на вызов» и «чтение без commit» проверяются в тестах сервисов
  (`uow_factory.call_count`, `uow.commit.call_count`).
- **U6.** Автокоммит в `__aexit__` отклонён: граница записи должна быть видна в сервисе, чтения
  не должны коммитить, перевод сбоев commit остаётся в `__aexit__` как сейчас.

**Правки:** `interfaces/unit_of_work.py`, `services/{customer,product,order}.py`,
`services/__init__.py`, `application/__init__.py`, `adapters/database/unit_of_work.py`,
`adapters/database/__init__.py`, `launchers/api.py`; тесты сервисов (фикстура
`uow_factory = Mock(return_value=uow)`, новый `test__new_unit_of_work_per_call`), conftest БД
(`partial(database.UnitOfWork, session_factory)`), `test_unit_of_work.py` (`uow_factory()`);
README (диаграммы, раздел «Транзакции», словарь имён, SOLID, паттерны: строка Abstract Factory →
«фабричная функция, не GoF», строка метода-обёртки удалена, чек-лист, тесты, отличия от
hex_arch), CLAUDE.md.

**Проверка:** ruff / mypy / pytest; кросс-ревью реализации двумя независимыми рецензентами.

**Итоги кросс-ревью реализации (2026-10-10).** Два независимых рецензента: A — архитектура и
чистота, B — корректность на реальной БД (эксперименты с мутантами и обрывами соединения).
BLOCKER нет; MAJOR один, найден обоими: unit-тесты чтений и `pay` проверяли только
`uow.<repo>.method_calls` и пропускали мутанты «чтение коммитит» и «commit после выхода из
контекста» (на реальной БД второй мутант молча теряет оплату). Принято: полные `uow.mock_calls`
в `get`/`find`/`pay` всех сервисов, точные аргументы `__aexit__` у `InsufficientStock`,
`commit.assert_not_called()` у not-found в `pay`/`cancel`; `database.UnitOfWork` после
`__aexit__` удаляет сессию и репозитории (вне контекста — `AttributeError`), вложенный вход —
`RuntimeError`, решение U2 уточнено: «объект на одну единицу работы за раз, повторный вход
после выхода открывает новую сессию»; тесты `TestLifecycle` и `test__lost_connection_on_commit`
(покрытие пути «ошибка на commit», потерянное с удалением `test_transactional.py`); smoke-тест
composition root `unit/launchers/test_api.py` (дыра типизации: `partial(database.UnitOfWork)`
без аргумента проходит mypy и падает только при вызове); конкретика composition root и тестов
убрана из докстрингов порта и адаптера, `Attributes` с приватными полями убран; тест «новый UoW
на вызов» перенесён в `TestGet` (класс на метод); README (две устаревшие мотивировки про
обёртку, слитые пункты раздела «Транзакции», таблица тестов) и CLAUDE.md. Отклонено: возврат
порядка «DTO → commit» (при `expire_on_commit=False` разницы нет, порядок одинаков во всех
записях). Вынесено пользователю: существующий баг вне скоупа — отказ в соединении при
`POSTGRES_HOST=localhost` приходит голым `OSError` (asyncio собирает отказы по IPv4 и IPv6)
и уходит как 500, а не 503 (`_is_transient` проверяет `ConnectionError`; правка —
`OSError | PoolTimeoutError` плюс тест с движком на закрытый порт); два стиля алиасов типов
(`type` в порте против присваивания в `api/lifespan.py`); при коммите дифф `docs/plan.md`
содержит и раздел 18 (план логирования) — делить по темам.
