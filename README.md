# Orders Service — учебный пример гексагональной архитектуры

Небольшой HTTP-сервис заказов (клиенты, товары, заказы), написанный как наглядный пример
**гексагональной архитектуры (Ports & Adapters)** с явным применением **SOLID**, паттернов
**GoF** и паттерна **Unit of Work**, объединяющего несколько репозиториев в одну транзакцию.

Стек: Python 3.12, FastAPI, SQLAlchemy 2 (async, asyncpg), PostgreSQL 17, Alembic, Pydantic v2,
uv, docker compose. Код, комментарии и документация — на русском, идентификаторы — на английском.
Докстринги — Google-стиль у каждого модуля, класса и функции (`Args` / `Returns` / `Raises`;
проверяет ruff `D`); пояснения к коду живут в докстрингах, а не в комментариях внутри функций
и классов.

Образцы, по которым построен проект: слои и правила слоёв — учебный репозиторий `hex_arch`;
устройство HTTP-адаптера и composition root — сервис `interactive_panels`. История
проектирования (план, кросс-ревью, принятые и отклонённые решения) — `docs/plan.md`.

---

## Быстрый старт

Деплой устроен по образцу `hex_arch/deployment`: всё, что относится к Docker, лежит в
`deployment/` — `dockerfiles/Dockerfile` (стадии `base → dependency-installer → builder →
tests / development / production`), `docker-composes/dev/docker-compose.dev.yml` и
`docker-composes/prod/docker-compose.prod.yml`, `entrypoints/` (скрипты запуска контейнеров),
`manage/` (скрипты управления стендом), `nginx_config/`.

1. Скопируйте `.env.example` в `.env` (Windows: `copy .env.example .env`) и при необходимости
   поправьте значения. Если порт 5432 на машине занят, задайте другие хостовые порты
   (`POSTGRES_PORT=5433`, `TEST_POSTGRES_PORT=5434`): внутри compose контейнеры ходят на
   `db:5432` и `db_for_tests:5432`.
2. Перейдите в каталог деплоя: `cd deployment`.
3. Запустите стенд (на Windows — из Git Bash):
   - разработка: `bash ./manage/start.sh --dev` (compose в foreground, логи в консоли);
   - production: `bash ./manage/start.sh` (в фоне).

Остановка, перезапуск и удаление — `stop.sh`, `restart.sh`, `remove.sh` с тем же флагом
`--dev`; подробнее — `deployment/manage/README.md`.

| Контейнер | Что делает | dev | prod |
|---|---|---|---|
| `api` | `entrypoint_api.sh`: ждёт БД, применяет миграции (`entrypoint_alembic.sh`), затем запускает uvicorn (`API_WORKER_COUNT`, `LOG_LEVEL`, `ADDITIONAL_API_ARGS`) | стадия `development`; порт `APP_PORT` (8000) наружу | стадия `production` — только установленный пакет, non-root; наружу не публикуется |
| `db` | PostgreSQL 17, volume с данными | публикуется на `POSTGRES_PORT` для локальных запусков | только внутри сети |
| `db_for_tests`, `api_for_tests` | отдельная БД без volume и прогон `tests/orders_service/integration` (`entrypoint_tests.sh`, стадия `tests`; unit-тесты выполняются при сборке образа) | падение тестов не роняет стенд — смотреть лог | `api` стартует только после успешного прогона |
| `pgadmin` | веб-интерфейс к БД (`PGADMIN_EMAIL` / `PGADMIN_PASSWORD`) | порт 5050 и через nginx `/pgadmin4/` | только через nginx |
| `nginx` | reverse proxy перед API и pgAdmin (`nginx_config/`) | `NGINX_EXTERNAL_PORT` (8080) | то же; `/docs`, `/redoc`, `/openapi.json` закрыты |

Ресурсы dev-стенда: API — http://localhost:8000/api/v1 напрямую и http://localhost:8080/api/v1
через nginx; Swagger UI — http://localhost:8000/docs и http://localhost:8080/docs; pgAdmin —
http://localhost:5050/ и http://localhost:8080/pgadmin4/. В production доступен только nginx:
http://localhost:8080/api/v1 и http://localhost:8080/pgadmin4/. Изменили порты в `.env` —
обновите адреса.

Локальная разработка поверх БД dev-стенда (поднимаются только `db` и `db_for_tests`):

```bash
uv sync
docker compose --env-file .env -f deployment/docker-composes/dev/docker-compose.dev.yml up -d db db_for_tests
uv run python -m orders_service.launchers.alembic_runner upgrade head
uv run uvicorn orders_service.launchers.api:app --reload
```

Проверки (все должны быть зелёными перед отчётом о готовности):

```bash
uv run ruff check .           # линтер, в т.ч. докстринги Google-стиля (D)
uv run ruff format --check .
uv run mypy .                 # strict, включая tests/
uv run pytest                 # unit + HTTP + интеграция с Postgres
```

Интеграционные тесты БД читают `TEST_POSTGRES_*` из окружения или `.env` (на dev-стенде это
`db_for_tests` на хостовом `TEST_POSTGRES_PORT`); если переменные не заданы, они пропускаются.

---

## Сквозной сценарий

```bash
API=http://localhost:8000/api/v1
curl -s -X POST $API/customers -H 'Content-Type: application/json' \
     -d '{"name": "Иван Петров", "email": "ivan@example.com"}'          # 201, id=1
curl -s -X POST $API/products -H 'Content-Type: application/json' \
     -d '{"name": "Кружка", "price": "10.00", "stock": 5}'               # 201, id=1
curl -s -X POST $API/products -H 'Content-Type: application/json' \
     -d '{"name": "Ложка", "price": "2.50", "stock": 10}'                # 201, id=2
curl -s -X POST $API/orders -H 'Content-Type: application/json' \
     -d '{"customer_id": 1, "lines": [{"product_id": 1, "quantity": 2},
                                      {"product_id": 2, "quantity": 8}]}'
# 201: subtotal "40.00", discount "2.00" (10 единиц → объёмная скидка 5%), total "38.00";
#      остатки списаны одной транзакцией вместе с созданием заказа
curl -s -X POST $API/orders/1/pay                                        # 200, status "paid"
curl -s -X POST $API/orders/1/cancel                                     # 400, order_transition_not_allowed
curl -s -X POST $API/orders -H 'Content-Type: application/json' \
     -d '{"customer_id": 1, "lines": [{"product_id": 1, "quantity": 99}]}'
# 400, insufficient_stock: {"product_id": 1, "requested": 99, "available": 3}
curl -s "$API/orders?customer_id=1&status=paid"                          # 200, {"items": [...]}
```

Тот же сценарий удобно прогнать из Swagger UI. В PowerShell вместо `curl` используйте
`Invoke-RestMethod` или `curl.exe` с экранированием кавычек.

---

## Архитектура

Три слоя, зависимости направлены внутрь: `launchers → adapters → application`.
Ядро (`application`) не импортирует ни SQLAlchemy, ни FastAPI.

```mermaid
flowchart LR
    subgraph launchers["launchers — composition root"]
        API_L["api.py<br/>Settings → Logger → Adapters → Application → Controllers"]
        ALEMBIC["alembic_runner.py"]
        CONFIG["config.py"]
    end
    subgraph adapters["adapters"]
        API["api — FastAPI<br/>create_app · Controller · create_router · error_handlers"]
        DB["database — SQLAlchemy<br/>UnitOfWorkFactory · UnitOfWork · репозитории · tables · mapping · alembic"]
    end
    subgraph application["application — ядро"]
        SERVICES["services<br/>Customer · Product · Order"]
        TX["transactional<br/>@transactional"]
        INTERFACES["interfaces (порты)<br/>CustomersRepo · ProductsRepo · OrdersRepo<br/>UnitOfWork · UnitOfWorkFactory"]
        ENTITIES["entities (домен)<br/>Customer · Product · Order · OrderLine<br/>DiscountPolicy · состояния заказа"]
        DTOS["dtos"]
        ERRORS["errors"]
    end
    API_L --> API
    API_L --> DB
    API_L --> SERVICES
    ALEMBIC --> DB
    API --> SERVICES
    DB -. реализует .-> INTERFACES
    SERVICES --> TX
    SERVICES --> INTERFACES
    SERVICES --> ENTITIES
    SERVICES --> DTOS
    SERVICES --> ERRORS
```

| Слой | Что внутри | Правила |
|---|---|---|
| `application/` | `entities.py` — весь домен; `services/` — сервис на сущность с набором методов; `interfaces/` — ABC только для **исходящих** портов; `dtos/` — Pydantic-модели входа/выхода и параметры поиска; `errors.py`; `transactional.py` — метод-обёртка транзакций | Между слоями передаются DTO и сущности, не `dict`/`list`. Входящих портов нет: контроллер зависит от конкретных `services.X` |
| `adapters/api/` | `create_app`, `create_lifespan`, `error_handlers`, `v1/controller.py`, `v1/router.py`, `v1/schemas` (`*Body.to_application()`), `v1/dtos` (`*Response.from_application()`) | **Обработчики — методы класса `Controller`, сервисы приходят в его конструктор. FastAPI-`Depends` не используется нигде.** `Path/Query/Body` — разбор запроса, не DI. Маршруты объявляются императивно (`add_api_route`) |
| `adapters/database/` | `settings`, `database` (движок и фабрика сессий), `tables`, `mapping` (императивный маппинг dataclass-сущностей), `repositories/`, `unit_of_work`, `alembic/`, `migrations/` | Реализации портов носят имена портов и различаются модулем: `interfaces.OrdersRepo` / `database.repositories.OrdersRepo` |
| `launchers/` | `api.py` — composition root HTTP-сервиса; `alembic_runner.py` — миграции; `config.py` — настройки уровня приложения | Граф собирается вручную в классах-неймспейсах при импорте модуля; все адаптеры и сервисы — синглтоны процесса |

---

## Путь запроса `POST /orders`

```mermaid
sequenceDiagram
    participant C as Клиент
    participant R as router / Controller.place_order
    participant S as services.Order.place
    participant T as @transactional
    participant F as database.UnitOfWorkFactory
    participant U as database.UnitOfWork
    participant E as entities
    C->>R: POST /api/v1/orders (OrderCreateBody)
    R->>S: place(dtos.NewOrderInfo)
    S->>T: вызов метода без uow
    T->>F: create()
    F-->>T: UnitOfWork(session, customers, products, orders)
    T->>S: method(self, uow, new_order_info)
    S->>U: customers.fetch_by_id
    S->>U: products.fetch_by_ids(for_update=True)
    S->>E: product.reserve(qty) · Order(...) · order.apply_discount(policy)
    S->>U: orders.add(order) → flush
    S-->>T: dtos.Order (собран до выхода из транзакции)
    T->>U: commit()
    T->>U: __aexit__ → rollback (холостой), close
    T-->>R: dtos.Order
    R-->>C: 201 OrderResponse
```

---

## Транзакции: Unit of Work и `@transactional`

- **Граница транзакции = публичный метод сервиса.** Метод помечается `@transactional`
  (`application/transactional.py`) и получает `uow` первым параметром после `self`; снаружи
  вызывается без него. Точная типизация — PEP 612 `Concatenate`, проверяется `mypy --strict`.
- **Новый UoW на каждый вызов.** Обёртка берёт `self.uow_factory` (порт
  `interfaces.UnitOfWorkFactory`) и создаёт UoW вместе с репозиториями на одной сессии —
  это и есть «UoW и репозитории создаются прямо в сервисе при вызове». Сервисы — синглтоны,
  запросы конкурентны, поэтому сессия не может жить в `self` сервиса.
- **Commit делает обёртка**, сервис никогда. При исключении commit не выполняется, откат делает
  `__aexit__` UoW, исключение уходит наружу. `rollback()` в порте отсутствует: он нужен только
  реализации.
- **Сущности живут внутри контекста.** Выход из `async with uow` откатывает незакоммиченное и
  сбрасывает состояние сущностей, поэтому сервисы собирают DTO до выхода и наружу отдают их.
- **Вложенных транзакций нет.** Транзакционный метод не вызывает другой транзакционный метод;
  общая логика выносится в приватные хелперы, принимающие `uow`.
- **Чтения тоже идут через UoW** (`get`, `find`): репозитории существуют только внутри него;
  commit пустой транзакции в Postgres — холостой.
- **Сбои хранилища** переводятся в одном месте — `database.UnitOfWork.__aexit__` — в
  `errors.StorageUnavailable` → HTTP 503 с `Retry-After`: обрыв соединения (у asyncpg это
  `InterfaceError` с флагом `connection_invalidated`, а не `OperationalError`), отказ в
  соединении, исчерпание пула, сбой сериализации `40001`, взаимная блокировка `40P01`.
  Мёртвые простаивающие соединения отсеивает `pool_pre_ping`. Нарушение уникальности email
  переводит репозиторий (`CustomerAlreadyExists` → 409).
- **Блокировки.** `ProductsRepo.fetch_by_ids(..., for_update=True)` выполняет
  `SELECT … ORDER BY id FOR UPDATE`: порядок захвата задаёт `ORDER BY` в самом запросе,
  сортировка списка в Python его не гарантирует. Под блокировкой строка перечитывается
  (`populate_existing`), даже если транзакция уже видела товар без блокировки. `place`
  блокирует только товары, `cancel` — строку заказа, затем товары; цикла нет. Проверено
  интеграционными тестами: детерминированная гонка за последнюю единицу, актуальность под
  блокировкой, захват двух строк в противоположном порядке → дедлок → 503.

---

## Статусы заказа

```mermaid
stateDiagram-v2
    [*] --> new
    new --> paid: pay()
    new --> cancelled: cancel() + возврат остатков
    paid --> [*]
    cancelled --> [*]
```

Недопустимый переход поднимает `OrderTransitionNotAllowed` (HTTP 400). Поведение по статусу
делегируется объектам состояния (`_NewOrderState`, `_FinalOrderState`) — паттерн State.

---

## Словарь имён

| Понятие | `entities` | `dtos` (вход / выход) | `services` | `interfaces` → `database` | `api/v1/schemas` → `api/v1/dtos` | `Controller` → `operation_id` |
|---|---|---|---|---|---|---|
| Клиент | `Customer` | `NewCustomerInfo` / `Customer` | `Customer.add/get` | `CustomersRepo` | `CustomerCreateBody` → `CustomerResponse` | `create_customer` → `createCustomer`, `get_customer` → `getCustomerById` |
| Товар | `Product` (`reserve/release`) | `NewProductInfo` / `Product` | `Product.add/get` | `ProductsRepo` | `ProductCreateBody` → `ProductResponse` | `create_product`, `get_product` |
| Заказ | `Order` (`apply_discount/pay/cancel`), `OrderLine`, `OrderStatus` | `NewOrderInfo{lines}`, `FindOrders` / `Order{lines}` | `Order.place/get/find/pay/cancel` | `OrdersRepo` | `OrderCreateBody{lines: [OrderLineCreateBody]}`, `OrderStatus` → `OrderResponse`, `OrderListResponse` | `place_order` → `placeOrder`, `get_order`, `list_orders`, `pay_order`, `cancel_order` |
| Транзакция | — | — | `@transactional`, `uow` первым после `self` | `UnitOfWork`, `UnitOfWorkFactory` → `database.UnitOfWork`, `database.UnitOfWorkFactory` | — | — |
| Ошибки | — | — | — | `errors.Error` → категории → `CustomerNotFound` … | `api/dtos.py: ErrorResponse` | — |

Правила: одинаковое имя в разных модулях различается модулем импорта; суффиксы `*Body` /
`*Response` — только на HTTP-краю; `New*Info` — входные DTO ядра; `Find*` — параметры поиска.
Предметные модули — в единственном числе (`dtos/order.py`), репозитории и их порты — во
множественном (`interfaces/orders.py`).

---

## SOLID

| Принцип | Где видно |
|---|---|
| **S** | Сервис — сценарии одной сущности; репозиторий — персистентность одной сущности; UoW — граница транзакции; `Controller` — перевод HTTP ↔ DTO; `router.py` — маршрутизация; `error_handlers.py` — ошибки → HTTP; `@transactional` — один сквозной аспект |
| **O** | Новая политика скидки — новый класс `DiscountPolicy` без правки `services.Order`; новый статус — новый класс состояния и строка в `_STATES`; новое хранилище — новая реализация `UnitOfWorkFactory` и репозиториев; новая ошибка — наследник категории, адаптер ошибок не меняется |
| **L** | Любая реализация портов (SQLAlchemy, `Mock(spec=…)` в тестах) подставляется вместо абстракции; все состояния заказа выполняют контракт `_OrderState` |
| **I** | Три узких порта репозиториев вместо одного универсального; порт `UnitOfWork` без `rollback()`; `UnitOfWorkFactory` отделён от `UnitOfWork`. Сознательный компромисс: один UoW на три репозитория — `services.Customer` получает порт, две трети которого не использует; UoW-порты по агрегатам для трёх сущностей были бы лишними |
| **D** | `application` зависит только от `interfaces` и доменных абстракций; адаптеры реализуют порты; сборка — в launcher; выбор `VolumeDiscount` и его параметры — в composition root и `.env` |

---

## Паттерны

| Паттерн | Класс / где | Что делает |
|---|---|---|
| Abstract Factory (GoF), в вырожденной форме | `interfaces.UnitOfWorkFactory` → `database.UnitOfWorkFactory.create()` | Одна операция создания; семейство объектов одной транзакции (сессия, три репозитория на ней, UoW) собирается внутри и отдаётся целиком как UoW |
| Strategy (GoF) | `entities.DiscountPolicy`: `NoDiscount`, `VolumeDiscount`; контекст — `Order.apply_discount` | Правило скидки подменяется в composition root, сервис знает только абстракцию |
| State (GoF) | `entities._OrderState`: `_NewOrderState`, `_FinalOrderState`; `Order.pay/cancel` | Поведение заказа зависит от статуса; недопустимый переход — исключение |
| Adapter (GoF, в широком смысле) | `adapters/database/repositories`, `database.UnitOfWork` | Приспосабливают `AsyncSession` к контрактам портов ядра |
| Null Object (не GoF) | `entities.NoDiscount` | Ноль вместо проверки «а есть ли политика» |
| Repository, Unit of Work, DTO (PoEAA, не GoF) | `interfaces/`, `adapters/database/`, `dtos/` | Персистентность за абстракцией, атомарная единица работы, передача данных между слоями |
| Метод-обёртка (Python-декоратор, аспект — **не** GoF Decorator) | `application/transactional.py` | Транзакция как сквозная функциональность; меняет сигнатуру и применяется статически |
| Composition Root | `launchers/api.py` | Единственное место, где видны все слои |

Маркер «Паттерн: X (GoF)» стоит в докстринге класса-носителя.

---

## Контракт API и ошибок

Префикс `/api/v1`, спецификация — `/openapi.json`, Swagger — `/docs`. Деньги (`price`,
`unit_price`, `discount`, `subtotal`, `total`) в JSON — **строки** с двумя знаками (`"19.99"`).

| Метод и путь | Назначение | Успех | Ошибки |
|---|---|---|---|
| `POST /customers` | зарегистрировать клиента | 201 | 400, 409 |
| `GET /customers/{id}` | клиент по id | 200 | 404 |
| `POST /products` | добавить товар с остатком | 201 | 400 |
| `GET /products/{id}` | товар по id | 200 | 404 |
| `POST /orders` | оформить заказ (резерв остатков, скидка, сохранение — одной транзакцией) | 201 | 400, 404 |
| `GET /orders?customer_id&status&limit&offset` | найти заказы | 200 | 400 |
| `GET /orders/{id}` | заказ по id | 200 | 404 |
| `POST /orders/{id}/pay` | `new → paid` | 200 | 400, 404 |
| `POST /orders/{id}/cancel` | `new → cancelled`, возврат остатков | 200 | 400, 404 |
| `GET /healthcheck` | служебная, вне схемы | 200 | — |

Любая ошибка — одно тело `{"error": "<текст>", "code": "<snake_case>", "context": {...}}`:

| Категория ядра (`errors.py`) | HTTP |
|---|---|
| `NotFoundError` (`CustomerNotFound`, `ProductNotFound`, `OrderNotFound`) | 404 |
| `ConflictError` (`CustomerAlreadyExists`) | 409 |
| `RuleViolationError` (`InsufficientStock`, `OrderTransitionNotAllowed`) | 400 |
| `StorageUnavailable` | 503 + `Retry-After: 1` |
| ошибка разбора запроса (`code: validation_error`, `context.details[]` с `loc/msg/type`) | 400 |
| ошибка ядра без категории, любое необработанное исключение | 500 (текст без подробностей) |

Автоматический ответ 422 FastAPI из схемы убран (`FastApiWithout422.openapi`): валидация
отдаёт 400. Ограничения тел запросов (`*Body`) — те же типы, что у DTO ядра
(`application/dtos/base.py`): границы входа совпадают с границами хранилища (`id`, `stock` и
`offset` — int4, `quantity` ≤ 1 000 000, строк в заказе ≤ 100, `limit` ≤ 200, email только
ASCII), поэтому вход, который БД не вместит, отклоняется как 400, а не падает в 500. Правило «один товар — одна строка
заказа» проверяется и на границе, и в `NewOrderInfo`. Ошибки маршрутизации (404 неизвестный
путь, 405 метод) — в той же форме тела с `code: http_error`.

---

## Как добавить сценарий

1. Домен: поведение — в сущность (`entities.py`), ошибка — наследник категории в `errors.py`,
   ограничения новых полей — общие типы в `dtos/base.py`.
2. Порт: метод в нужном `interfaces/*Repo`; при новой сущности — новый порт, свойство в
   `interfaces.UnitOfWork`, свойство и параметр конструктора в `database.UnitOfWork`, создание
   репозитория в `database.UnitOfWorkFactory.create()`, мок-репозиторий в фикстуре `uow`
   модулей `tests/orders_service/unit/application/services/test_*.py`.
3. Адаптер БД: реализация в `adapters/database/repositories/`, таблица в `tables.py`, маппинг в
   `mapping.py`, миграция: `uv run python -m orders_service.launchers.alembic_runner revision
   --autogenerate -m "<slug>" --rev-id 0002`, затем `uv run ruff check --fix` на файле миграции.
4. Сервис: метод с `@transactional`, `uow` первым после `self`, DTO собирается внутри.
5. HTTP: `*Body`/`*Response` в `api/v1/schemas` и `api/v1/dtos`, метод `Controller`,
   `add_api_route` в `router.py` с `operation_id`, тегом и картой ответов.
6. Тесты: unit сервиса на `MagicMock(spec=UnitOfWork)`, HTTP-тест контроллера на
   `Mock(services.X)`, интеграционный тест репозитория/UoW при новой работе с БД (данные —
   в `test_data.py`); стиль — как в hex_arch: класс на метод, `# Setup / # Call / # Assert`.
7. Сборка: новый сервис — в `launchers/api.py` (`Application` и `Controllers`).

---

## Тесты

Раскладка повторяет образец `hex_arch` (`tests/med_sharing_system/...`): `tests/orders_service/`
зеркалит слои пакета, каждый каталог — пакет с `__init__.py`.

| Каталог | Что проверяет | Инфраструктура |
|---|---|---|
| `unit/application/services/` | сервисы на моках портов: `MagicMock(spec=interfaces.UnitOfWork)` с `Mock(interfaces.XRepo)`, порядок вызовов через `uow.mock_calls`; классы по методам (`TestAdd`, `TestGet`, `TestPlace` …), параметризация «что вернул репозиторий → что отдал сервис» | нет |
| `unit/application/` | сущности (`test_entities.py`: State, Strategy, остатки), DTO (`test_dtos.py`: нормализация и границы), обёртка `@transactional` (`test_transactional.py`: commit / отказ от commit / новый UoW на вызов) | нет |
| `unit/adapters/api/v1/` | `test_schemas.py` — граничные входы `*Body` принимаются DTO ядра (общие типы `dtos.base`) | нет |
| `integration/adapters/api/controllers/` | настоящий FastAPI над `Mock(services.X)` (`conftest.py`: `<x>_service`, `app`, `client`); модуль на ресурс, класс на обработчик (`TestCreateCustomer`, `TestListOrders` …); `test_error_handlers.py` — 503 с `Retry-After`, 500 без подробностей, единое тело 404/405, контракт OpenAPI | нет |
| `integration/adapters/database/` | `conftest.py` — `create_test_db` (схема через `metadata.create_all`, без миграций), `session` (откат после теста), `uow_factory`; `test_data.py` — наборы `*_DATA` и `insert_*`; `repositories/test_*.py` — `fill_db` autouse, класс на метод репозитория (`TestFetchById`, `TestFetchAll`, `TestAdd` …); `test_unit_of_work.py` — транзакции коммитятся по-настоящему: атомарность, откат на второй строке, оплата и отмена, `FOR UPDATE` (гонка, актуальность, повторная блокировка), дедлок и обрыв соединения → `StorageUnavailable` | `TEST_POSTGRES_*` (на dev-стенде — контейнер `db_for_tests`), иначе `skip`; схема пересоздаётся на каждый тест |

Соглашения (как в hex_arch): секции `# SETUP` / `# TESTS` в модуле, фикстуры с явным `scope`
рядом с тестами, имена `test__<метод>` и `test__<ошибка>`, комментарии `# Setup`, `# Call`,
`# Assert`, проверки через `method_calls`. Единственное отличие от образца — полные аннотации
типов: тесты проверяются ruff (`ANN`) и mypy strict.

Особенности моков: у `MagicMock(spec=UnitOfWork)` нужно явно задать
`__aenter__.return_value = uow` и присвоить репозитории (spec не протаскивается в свойства);
сервисы мокаются `Mock(services.X)`, не `create_autospec` (обёртка оставляет `__wrapped__`).

---

## Отличия от hex_arch (глоссарий)

| hex_arch | Здесь | Почему |
|---|---|---|
| Falcon + gunicorn/gevent, sync SQLAlchemy | FastAPI + uvicorn, async SQLAlchemy (asyncpg) | async-стек; HTTP-адаптер по образцу interactive_panels |
| `TransactionContext` (сессия на поток, счётчик вложенности) + реестр `DecoratedFunctionRegistry.apply_decorators(...)` в launcher | `UnitOfWorkFactory` в конструкторе сервиса + `@transactional` | thread-local не живёт в asyncio; без глобальной мутации классов; UoW и репозитории создаются на вызов |
| Репозитории — синглтоны с сессией из контекста | Репозитории создаются фабрикой UoW на каждую транзакцию | то же |
| `application/schemas` для параметров поиска | `FindOrders` в `dtos/order.py` | слово `schemas` занято HTTP-швом с другим смыслом |
| Pydantic v1, `validate_arguments` на методах сервисов | Pydantic v2, без `validate_call` | вход валидируется при построении DTO на границе |
| `ErrorMeta` (метакласс) | `__init_subclass__` + категории ошибок | меньше магии; категории дают OCP в обработчике ошибок |
| Стратегия поиска `_XStrategySelector` → 2ⁿ методов репозитория | `OrdersRepo.fetch_all(FindOrders)` с динамическим `WHERE` | Strategy показана на скидке |
| `deployment/backend/` в монорепозитории, `.env` в `components/backend/` | `deployment/` и `.env` в корне | один компонент — плоская раскладка; состав тот же: Dockerfile со стадиями (`dockerfiles/`), compose dev/prod (`docker-composes/`), `entrypoints/`, `manage/`, `nginx_config/`; подготовленных данных (`test_data.py`) нет |
| `db` доступна только внутри сети compose | в dev `db` и `db_for_tests` публикуются на `POSTGRES_PORT` / `TEST_POSTGRES_PORT` | локальные `uv run uvicorn --reload` и `pytest` без второго Postgres; в prod — как в образце |
| `where(entities.X.attr == …)` в запросах | `where(tables.x.c.col == …)` | под `mypy --strict` атрибуты dataclass-сущностей не `InstrumentedAttribute`; выборка всё равно возвращает сущности |
| Без линтера | ruff + mypy strict | типизация обёртки — часть демонстрации |

---

## Что сознательно не сделано

Аутентификация, брокеры сообщений, CI, фронтенд и CORS, TLS и prod-hardening, i18n, UoW-порты по агрегатам, вложенные транзакции и read-only режим обёртки — всё это
вне учебного минимума. `docs/plan.md` после реализации остаётся историей проектирования;
действующие правила — в этом README и в докстрингах.
