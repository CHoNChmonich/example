"""Unit of Work на реальном PostgreSQL: атомарность, откат, блокировки, сбои хранилища.

В отличие от тестов репозиториев, здесь транзакции коммитятся по-настоящему: данные
готовятся и фиксируются в ``fill_db``, а схема удаляется после теста (``create_test_db``).
"""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from orders_service.adapters.database import tables
from orders_service.application import dtos, entities, errors, interfaces, services

from . import test_data

# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
WAIT_TIMEOUT = 15  # секунд; защищает прогон от зависания, если участник гонки упадёт


@pytest.fixture(scope="function", autouse=True)
async def fill_db(session: AsyncSession) -> dict[str, list[int]]:
    customer_ids: list[int] = await test_data.insert_customers(session)
    product_ids: list[int] = await test_data.insert_products(session)
    await session.commit()  # UoW работает в других сессиях — данные должны быть зафиксированы
    return {"customer_ids": customer_ids, "product_ids": product_ids}


@pytest.fixture(scope="function")
def service(uow_factory: interfaces.UnitOfWorkFactory) -> services.Order:
    return services.Order(uow_factory=uow_factory, discount_policy=entities.NoDiscount())


def _new_order(customer_id: int, *lines: tuple[int, int]) -> dtos.NewOrderInfo:
    return dtos.NewOrderInfo(
        customer_id=customer_id,
        lines=[dtos.NewOrderLineInfo(product_id=pid, quantity=qty) for pid, qty in lines],
    )


async def _wait_for_lock_waiter(engine: AsyncEngine) -> None:
    """Дождаться, пока вторая транзакция встанет в очередь на блокировку строки."""
    query = text(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE datname = current_database() AND wait_event_type = 'Lock'"
    )
    for _ in range(200):
        async with engine.connect() as connection:
            if (await connection.execute(query)).scalar_one():
                return
        await asyncio.sleep(0.05)
    raise AssertionError("вторая транзакция не встала в ожидание блокировки")


async def _terminate_other_backends(engine: AsyncEngine) -> None:
    """Оборвать все остальные соединения с тестовой БД — имитация потери сети."""
    async with engine.connect() as connection:
        await connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
        )


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestPlace:
    async def test__writes_order_lines_and_stock_atomically(
        self, service: services.Order, session: AsyncSession, fill_db: dict[str, list[int]]
    ) -> None:
        # Setup
        customer_id: int = fill_db["customer_ids"][0]
        mug_id, spoon_id, _ = fill_db["product_ids"]  # остатки 5 и 10

        # Call
        placed = await service.place(_new_order(customer_id, (mug_id, 2), (spoon_id, 8)))

        # Assert
        stored = await service.get(placed.id)
        assert stored == placed
        assert [(line.product_id, line.quantity) for line in stored.lines] == [
            (mug_id, 2),
            (spoon_id, 8),
        ]
        assert stored.total == Decimal("40.00")
        assert await test_data.select_stock(mug_id, session) == 3
        assert await test_data.select_stock(spoon_id, session) == 2

    async def test__insufficient_stock_on_second_line_leaves_nothing_behind(
        self, service: services.Order, session: AsyncSession, fill_db: dict[str, list[int]]
    ) -> None:
        # Setup
        customer_id: int = fill_db["customer_ids"][0]
        mug_id, _, empty_id = fill_db["product_ids"]  # остатки 5 и 0

        # Call and Assert
        with pytest.raises(errors.InsufficientStock):
            await service.place(_new_order(customer_id, (mug_id, 2), (empty_id, 1)))

        # Первая строка уже списала остаток кружки в памяти — откат UoW вернул всё.
        assert await test_data.select_stock(mug_id, session) == 5
        assert await test_data.count_rows(tables.orders, session) == 0


class TestPay:
    async def test__pay_persists_status(
        self, service: services.Order, fill_db: dict[str, list[int]]
    ) -> None:
        # Setup
        customer_id: int = fill_db["customer_ids"][0]
        mug_id: int = fill_db["product_ids"][0]
        placed = await service.place(_new_order(customer_id, (mug_id, 1)))

        # Call
        paid = await service.pay(placed.id)

        # Assert
        assert paid.status is entities.OrderStatus.PAID
        assert (await service.get(placed.id)).status is entities.OrderStatus.PAID
        with pytest.raises(errors.OrderTransitionNotAllowed):
            await service.cancel(placed.id)


class TestCancel:
    async def test__cancel_returns_stock(
        self, service: services.Order, session: AsyncSession, fill_db: dict[str, list[int]]
    ) -> None:
        # Setup
        customer_id: int = fill_db["customer_ids"][0]
        mug_id: int = fill_db["product_ids"][0]
        placed = await service.place(_new_order(customer_id, (mug_id, 3)))
        assert await test_data.select_stock(mug_id, session) == 2

        # Call
        cancelled = await service.cancel(placed.id)

        # Assert
        assert cancelled.status is entities.OrderStatus.CANCELLED
        assert await test_data.select_stock(mug_id, session) == 5
        with pytest.raises(errors.OrderTransitionNotAllowed):
            await service.pay(placed.id)


class TestForUpdate:
    async def test__serializes_stock_reservation(
        self,
        service: services.Order,
        uow_factory: interfaces.UnitOfWorkFactory,
        create_test_db: AsyncEngine,
        session: AsyncSession,
        fill_db: dict[str, list[int]],
    ) -> None:
        """Две транзакции претендуют на последнюю единицу: FOR UPDATE пускает их по очереди."""
        # Setup
        customer_id: int = fill_db["customer_ids"][0]
        mug_id: int = fill_db["product_ids"][0]
        async with uow_factory() as uow:  # остаётся ровно одна единица
            (mug,) = await uow.products.fetch_by_ids([mug_id], for_update=True)
            mug.reserve(4)
            await uow.commit()
        locked = asyncio.Event()
        release = asyncio.Event()

        async def competitor() -> None:
            async with uow_factory() as uow:
                (product,) = await uow.products.fetch_by_ids([mug_id], for_update=True)
                locked.set()
                await release.wait()
                product.reserve(1)
                await uow.commit()

        async def place_last_unit() -> BaseException | None:
            await locked.wait()
            try:
                await service.place(_new_order(customer_id, (mug_id, 1)))
            except errors.Error as error:
                return error
            return None

        # Call
        async with asyncio.timeout(WAIT_TIMEOUT):
            competitor_task = asyncio.create_task(competitor())
            placing_task = asyncio.create_task(place_last_unit())
            await locked.wait()
            await _wait_for_lock_waiter(create_test_db)  # заказ ждёт строку, а не старый остаток
            release.set()
            await competitor_task
            outcome = await placing_task

        # Assert
        assert isinstance(outcome, errors.InsufficientStock)
        assert await test_data.select_stock(mug_id, session) == 0
        assert await test_data.count_rows(tables.orders, session) == 0

    async def test__refreshes_product_read_earlier_without_lock(
        self, uow_factory: interfaces.UnitOfWorkFactory, fill_db: dict[str, list[int]]
    ) -> None:
        """Под блокировкой товар перечитывается, даже если эта же транзакция уже видела его."""
        # Setup
        mug_id: int = fill_db["product_ids"][0]

        # Call and Assert
        async with uow_factory() as uow:
            stale = await uow.products.fetch_by_id(mug_id)  # без блокировки: остаток 5
            async with uow_factory() as other:
                (product,) = await other.products.fetch_by_ids([mug_id], for_update=True)
                product.reserve(4)
                await other.commit()
            (locked,) = await uow.products.fetch_by_ids([mug_id], for_update=True)
            assert locked is stale
            assert locked.stock == 1

    async def test__relocking_keeps_pending_reservation(
        self, uow_factory: interfaces.UnitOfWorkFactory, fill_db: dict[str, list[int]]
    ) -> None:
        """Повторная блокировка в той же транзакции не теряет ещё не сохранённый резерв:
        autoflush сбрасывает его в БД перед SELECT с populate_existing."""
        # Setup
        mug_id: int = fill_db["product_ids"][0]

        # Call and Assert
        async with uow_factory() as uow:
            (product,) = await uow.products.fetch_by_ids([mug_id], for_update=True)
            product.reserve(2)
            (again,) = await uow.products.fetch_by_ids([mug_id], for_update=True)
            assert again is product
            assert again.stock == 3

    async def test__place_and_cancel_on_shared_products_complete_without_deadlock(
        self, service: services.Order, session: AsyncSession, fill_db: dict[str, list[int]]
    ) -> None:
        """Сценарий «оформление и отмена одних и тех же товаров» завершается без взаимной
        блокировки. Порядок захвата внутри одного запроса задаёт ``ORDER BY id``; нарушить его
        одним запросом нельзя, поэтому роль ``ORDER BY`` показывает тест дедлока ниже."""
        # Setup
        customer_id: int = fill_db["customer_ids"][0]
        first_id, second_id, _ = fill_db["product_ids"]  # остатки 5 и 10
        placed = await service.place(_new_order(customer_id, (second_id, 1), (first_id, 1)))

        # Call
        async with asyncio.timeout(WAIT_TIMEOUT):
            results = await asyncio.gather(
                *[
                    service.place(_new_order(customer_id, (first_id, 1), (second_id, 1)))
                    for _ in range(3)
                ],
                service.cancel(placed.id),
                return_exceptions=True,
            )

        # Assert
        failures = [result for result in results if isinstance(result, BaseException)]
        assert failures == []
        assert await test_data.select_stock(first_id, session) == 2
        assert await test_data.select_stock(second_id, session) == 7


class TestStorageUnavailable:
    async def test__deadlock(
        self, uow_factory: interfaces.UnitOfWorkFactory, fill_db: dict[str, list[int]]
    ) -> None:
        """Захват двух строк в противоположном порядке разными запросами: PostgreSQL прерывает
        одну транзакцию (sqlstate 40P01), UoW переводит это в ``StorageUnavailable``."""
        # Setup
        first_id, second_id, _ = fill_db["product_ids"]
        first_locked = asyncio.Event()
        second_locked = asyncio.Event()

        async def lock_in_order(
            first: int, second: int, mine: asyncio.Event, other: asyncio.Event
        ) -> None:
            async with uow_factory() as uow:
                await uow.products.fetch_by_ids([first], for_update=True)
                mine.set()
                await other.wait()
                await uow.products.fetch_by_ids([second], for_update=True)
                await uow.commit()

        # Call
        async with asyncio.timeout(WAIT_TIMEOUT):
            results = await asyncio.gather(
                lock_in_order(first_id, second_id, first_locked, second_locked),
                lock_in_order(second_id, first_id, second_locked, first_locked),
                return_exceptions=True,
            )

        # Assert
        failures = [result for result in results if isinstance(result, BaseException)]
        assert len(failures) == 1
        assert isinstance(failures[0], errors.StorageUnavailable)
        cause = failures[0].__cause__
        assert getattr(getattr(cause, "orig", None), "sqlstate", None) == "40P01"

    async def test__lost_connection(
        self,
        uow_factory: interfaces.UnitOfWorkFactory,
        create_test_db: AsyncEngine,
        fill_db: dict[str, list[int]],
    ) -> None:
        # Setup
        mug_id: int = fill_db["product_ids"][0]

        # Call and Assert
        with pytest.raises(errors.StorageUnavailable):
            async with uow_factory() as uow:
                await uow.products.fetch_by_id(mug_id)  # соединение транзакции открыто
                await _terminate_other_backends(create_test_db)  # «сеть упала»
                await uow.products.fetch_by_ids([mug_id], for_update=True)

    async def test__lost_connection_on_commit(
        self,
        uow_factory: interfaces.UnitOfWorkFactory,
        create_test_db: AsyncEngine,
        session: AsyncSession,
        fill_db: dict[str, list[int]],
    ) -> None:
        # Setup
        mug_id: int = fill_db["product_ids"][0]

        # Call and Assert
        with pytest.raises(errors.StorageUnavailable):
            async with uow_factory() as uow:
                (product,) = await uow.products.fetch_by_ids([mug_id], for_update=True)
                product.reserve(1)
                await _terminate_other_backends(create_test_db)  # «сеть упала» перед commit
                await uow.commit()

        assert await test_data.select_stock(mug_id, session) == 5


class TestLifecycle:
    async def test__repositories_unavailable_after_exit(
        self, uow_factory: interfaces.UnitOfWorkFactory
    ) -> None:
        # Call
        async with uow_factory() as uow:
            pass

        # Assert
        with pytest.raises(AttributeError):
            _ = uow.products
        with pytest.raises(AttributeError):
            await uow.commit()

    async def test__nested_enter_rejected(self, uow_factory: interfaces.UnitOfWorkFactory) -> None:
        # Call and Assert
        async with uow_factory() as uow:
            with pytest.raises(RuntimeError):
                async with uow:
                    pass

    async def test__sequential_reuse_opens_new_session(
        self, uow_factory: interfaces.UnitOfWorkFactory, fill_db: dict[str, list[int]]
    ) -> None:
        # Setup
        mug_id: int = fill_db["product_ids"][0]
        uow = uow_factory()

        # Call
        async with uow:
            first = await uow.products.fetch_by_id(mug_id)
        async with uow:
            second = await uow.products.fetch_by_id(mug_id)

        # Assert: разные сессии — разные identity map
        assert first is not None
        assert second is not None
        assert first is not second
