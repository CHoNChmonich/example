"""Спаны SQL, пула и единицы работы на реальном PostgreSQL."""

import asyncio

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from orders_service.adapters import database, tracing
from orders_service.application import errors, interfaces, services

from . import test_data

# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
HOLD_SECONDS = 0.2  # сколько транзакция A держит единственный слот пула после старта B
SHORT_POOL_TIMEOUT = 0.2  # секунд; ожидание слота, которое гарантированно истекает в тесте


@pytest.fixture(scope="function", autouse=True)
async def fill_db(session: AsyncSession) -> dict[str, list[int]]:
    product_ids: list[int] = await test_data.insert_products(session)
    await session.commit()
    return {"product_ids": product_ids}


@pytest.fixture(scope="function")
def traced_pool_uow_factory(traced_pool_engine: AsyncEngine) -> interfaces.UnitOfWorkFactory:
    session_factory = async_sessionmaker(traced_pool_engine, expire_on_commit=False)

    def factory() -> interfaces.UnitOfWork:
        return tracing.TracedUnitOfWork(database.UnitOfWork(session_factory))

    return factory


def _by_name(spans: InMemorySpanExporter, name: str) -> list[ReadableSpan]:
    return [span for span in spans.get_finished_spans() if span.name == name]


def _assert_child(child: ReadableSpan, parent: ReadableSpan) -> None:
    parent_context = parent.get_span_context()
    assert child.parent is not None
    assert parent_context is not None
    assert child.parent.span_id == parent_context.span_id


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestInstrument:
    async def test__query_span_is_child_of_unit_of_work(
        self,
        traced_uow_factory: interfaces.UnitOfWorkFactory,
        fill_db: dict[str, list[int]],
        spans: InMemorySpanExporter,
    ) -> None:
        # Setup
        mug_id: int = fill_db["product_ids"][0]
        spans.clear()

        # Call
        async with traced_uow_factory() as uow:
            await uow.products.fetch_by_id(mug_id)
            await uow.commit()

        # Assert
        (unit_of_work,) = _by_name(spans, "unit_of_work")
        (select,) = _by_name(spans, "SELECT")
        assert select.kind is SpanKind.CLIENT
        _assert_child(select, unit_of_work)
        assert select.attributes is not None
        assert select.attributes["db.system"] == "postgresql"
        assert select.attributes["db.operation"] == "SELECT"
        assert str(select.attributes["db.statement"]).startswith("SELECT")
        assert unit_of_work.attributes is not None
        assert unit_of_work.attributes[tracing.OUTCOME_ATTRIBUTE] == "committed"

    async def test__failed_query_marks_span(
        self, session: AsyncSession, spans: InMemorySpanExporter
    ) -> None:
        # Setup
        spans.clear()

        # Call
        with pytest.raises(ProgrammingError):
            await session.execute(text("SELECT nothing FROM nowhere"))

        # Assert
        (select,) = _by_name(spans, "SELECT")
        assert select.status.status_code is StatusCode.ERROR
        assert [event.name for event in select.events] == ["exception"]

    async def test__failed_query_inside_unit_of_work(
        self, traced_uow_factory: interfaces.UnitOfWorkFactory, spans: InMemorySpanExporter
    ) -> None:
        # Setup
        spans.clear()

        # Call: сырой запрос через сессию репозитория — ошибка SQL внутри единицы работы
        with pytest.raises(ProgrammingError):
            async with traced_uow_factory() as uow:
                assert isinstance(uow.products, database.repositories.ProductsRepo)
                await uow.products.session.execute(text("SELECT nothing FROM nowhere"))

        # Assert: SQL-спан с ошибкой — ребёнок unit_of_work, сам unit_of_work — ERROR
        (unit_of_work,) = _by_name(spans, "unit_of_work")
        (select,) = _by_name(spans, "SELECT")
        _assert_child(select, unit_of_work)
        assert select.status.status_code is StatusCode.ERROR
        assert unit_of_work.status.status_code is StatusCode.ERROR
        assert not trace.get_current_span().get_span_context().is_valid


class TestTracedPool:
    async def test__connect_span_precedes_first_query(
        self,
        traced_pool_uow_factory: interfaces.UnitOfWorkFactory,
        fill_db: dict[str, list[int]],
        spans: InMemorySpanExporter,
    ) -> None:
        # Setup
        mug_id: int = fill_db["product_ids"][0]
        spans.clear()

        # Call: два запроса одной транзакции — соединение берётся один раз
        async with traced_pool_uow_factory() as uow:
            await uow.products.fetch_by_id(mug_id)
            await uow.products.fetch_by_id(mug_id)

        # Assert: спан пула — ребёнок unit_of_work, раньше первого SELECT, состояние до взятия
        (unit_of_work,) = _by_name(spans, "unit_of_work")
        (connect,) = _by_name(spans, "pool.connect")
        first_select, _ = _by_name(spans, "SELECT")
        _assert_child(connect, unit_of_work)
        assert connect.start_time is not None
        assert first_select.start_time is not None
        assert connect.end_time is not None
        assert connect.start_time < connect.end_time <= first_select.start_time
        assert connect.attributes is not None
        assert connect.attributes[tracing.POOL_SIZE_ATTRIBUTE] == 1
        assert connect.attributes[tracing.POOL_CHECKED_IN_ATTRIBUTE] == 0
        assert connect.attributes[tracing.POOL_CHECKED_OUT_ATTRIBUTE] == 0

    async def test__connect_span_covers_waiting_for_free_slot(
        self,
        traced_pool_uow_factory: interfaces.UnitOfWorkFactory,
        fill_db: dict[str, list[int]],
        spans: InMemorySpanExporter,
    ) -> None:
        # Setup: единственный слот пула держит транзакция A, пока B не встанет в ожидание
        mug_id: int = fill_db["product_ids"][0]
        holder_ready = asyncio.Event()
        waiter_started = asyncio.Event()
        spans.clear()

        async def hold_slot() -> None:
            async with traced_pool_uow_factory() as uow:
                await uow.products.fetch_by_id(mug_id)
                holder_ready.set()
                await waiter_started.wait()
                await asyncio.sleep(HOLD_SECONDS)

        async def wait_for_slot() -> None:
            await holder_ready.wait()
            waiter_started.set()
            async with traced_pool_uow_factory() as uow:
                await uow.products.fetch_by_id(mug_id)

        # Call
        await asyncio.gather(hold_slot(), wait_for_slot())

        # Assert: спан взятия у B начался при занятом слоте, длился не меньше задержки A
        # и закончился не раньше выхода A (на Windows метки времени могут совпасть)
        holder_uow, waiter_uow = _by_name(spans, "unit_of_work")
        holder_connect, waiter_connect = _by_name(spans, "pool.connect")
        _assert_child(waiter_connect, waiter_uow)
        assert waiter_connect.start_time is not None
        assert holder_uow.end_time is not None
        assert waiter_connect.end_time is not None
        assert waiter_connect.start_time < holder_uow.end_time <= waiter_connect.end_time
        assert waiter_connect.end_time - waiter_connect.start_time >= HOLD_SECONDS * 10**9 // 2
        assert holder_connect.attributes is not None
        assert waiter_connect.attributes is not None
        assert holder_connect.attributes[tracing.POOL_CHECKED_OUT_ATTRIBUTE] == 0
        assert waiter_connect.attributes[tracing.POOL_CHECKED_OUT_ATTRIBUTE] == 1

    async def test__pool_timeout_marks_span_and_becomes_storage_unavailable(
        self,
        test_database_url: str,
        create_test_db: AsyncEngine,
        fill_db: dict[str, list[int]],
        spans: InMemorySpanExporter,
    ) -> None:
        # Setup: тот же пул на один слот, но с коротким таймаутом ожидания
        mug_id: int = fill_db["product_ids"][0]
        engine = create_async_engine(
            test_database_url,
            poolclass=database.spans.TracedPool,
            pool_size=1,
            max_overflow=0,
            pool_timeout=SHORT_POOL_TIMEOUT,
        )
        database.spans.instrument(engine)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        def factory() -> interfaces.UnitOfWork:
            return tracing.TracedUnitOfWork(database.UnitOfWork(session_factory))

        spans.clear()

        # Call: слот держит первая транзакция, вторая не дожидается соединения
        try:
            async with factory() as holder:
                await holder.products.fetch_by_id(mug_id)
                with pytest.raises(errors.StorageUnavailable) as excinfo:
                    async with factory() as waiter:
                        await waiter.products.fetch_by_id(mug_id)
        finally:
            await engine.dispose()

        # Assert: таймаут пула — временный сбой хранилища; спан пула и единицы работы — ERROR
        assert isinstance(excinfo.value.__cause__, PoolTimeoutError)
        holder_connect, waiter_connect = _by_name(spans, "pool.connect")
        waiter_uow, _ = _by_name(spans, "unit_of_work")
        assert holder_connect.status.status_code is StatusCode.UNSET
        assert waiter_connect.status.status_code is StatusCode.ERROR
        (event,) = waiter_connect.events
        assert event.attributes is not None
        assert str(event.attributes["exception.type"]).endswith("TimeoutError")
        assert waiter_connect.attributes is not None
        assert waiter_connect.attributes[tracing.POOL_CHECKED_OUT_ATTRIBUTE] == 1
        assert waiter_uow.status.status_code is StatusCode.ERROR
        assert waiter_uow.attributes is not None
        assert waiter_uow.attributes[tracing.OUTCOME_ATTRIBUTE] == "rolled_back"


class TestTracedService:
    async def test__scenario_tree_on_real_database(
        self,
        traced_uow_factory: interfaces.UnitOfWorkFactory,
        fill_db: dict[str, list[int]],
        spans: InMemorySpanExporter,
    ) -> None:
        # Setup: сервис ядра под декоратором, как собирает composition root
        mug_id: int = fill_db["product_ids"][0]
        product = tracing.TracedProduct(services.Product(uow_factory=traced_uow_factory))
        spans.clear()

        # Call
        found = await product.get(mug_id)

        # Assert: Product.get → unit_of_work → SELECT
        assert found.id == mug_id
        (scenario,) = _by_name(spans, "Product.get")
        (unit_of_work,) = _by_name(spans, "unit_of_work")
        (select,) = _by_name(spans, "SELECT")
        _assert_child(unit_of_work, scenario)
        _assert_child(select, unit_of_work)
        assert scenario.status.status_code is StatusCode.UNSET
        assert not trace.get_current_span().get_span_context().is_valid
