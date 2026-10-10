from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orders_service.adapters.database import repositories, tables
from orders_service.application import entities

from .. import test_data


# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
@pytest.fixture(scope="function", autouse=True)
async def fill_db(session: AsyncSession) -> dict[str, list[int]]:
    product_ids: list[int] = await test_data.insert_products(session)
    return {"product_ids": product_ids}


@pytest.fixture(scope="function")
def repo(session: AsyncSession) -> repositories.ProductsRepo:
    return repositories.ProductsRepo(session)


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestFetchById:
    async def test__fetch_by_id(
        self, repo: repositories.ProductsRepo, fill_db: dict[str, list[int]]
    ) -> None:
        # Setup
        product_id: int = fill_db["product_ids"][0]

        # Call
        result = await repo.fetch_by_id(product_id)

        # Assert
        assert isinstance(result, entities.Product)
        assert result.id == product_id
        assert result.price == test_data.PRODUCTS_DATA[0]["price"]

    async def test__product_not_found(
        self, repo: repositories.ProductsRepo, fill_db: dict[str, list[int]]
    ) -> None:
        # Call
        result = await repo.fetch_by_id(max(fill_db["product_ids"]) + 1)

        # Assert
        assert result is None


class TestFetchByIds:
    async def test__fetch_by_ids(
        self, repo: repositories.ProductsRepo, fill_db: dict[str, list[int]]
    ) -> None:
        # Setup
        product_ids: list[int] = fill_db["product_ids"]

        # Call
        result = await repo.fetch_by_ids(list(reversed(product_ids)))

        # Assert
        assert [product.id for product in result] == product_ids  # по возрастанию id
        assert all(isinstance(product, entities.Product) for product in result)

    async def test__missing_ids_are_skipped(
        self, repo: repositories.ProductsRepo, fill_db: dict[str, list[int]]
    ) -> None:
        # Setup
        product_id: int = fill_db["product_ids"][0]
        missing_id: int = max(fill_db["product_ids"]) + 1

        # Call
        result = await repo.fetch_by_ids([missing_id, product_id])

        # Assert
        assert [product.id for product in result] == [product_id]

    async def test__empty_ids(self, repo: repositories.ProductsRepo) -> None:
        # Call
        result = await repo.fetch_by_ids([])

        # Assert
        assert list(result) == []

    async def test__for_update_locks_rows(
        self,
        repo: repositories.ProductsRepo,
        session: AsyncSession,
        session_factory: async_sessionmaker[AsyncSession],
        fill_db: dict[str, list[int]],
    ) -> None:
        # Setup
        product_id: int = fill_db["product_ids"][0]
        await session.commit()  # строка должна быть видна второй сессии
        await repo.fetch_by_ids([product_id], for_update=True)
        nowait_lock = (
            select(tables.products.c.id)
            .where(tables.products.c.id == product_id)
            .with_for_update(nowait=True)
        )

        # Call and Assert
        async with session_factory() as other_session:
            with pytest.raises(DBAPIError) as exc_info:
                await other_session.execute(nowait_lock)

        assert getattr(exc_info.value.orig, "sqlstate", None) == "55P03"  # lock_not_available


class TestAdd:
    async def test__add(self, repo: repositories.ProductsRepo, session: AsyncSession) -> None:
        # Setup
        before_count = await test_data.count_rows(tables.products, session)

        # Call
        result = await repo.add(
            entities.Product(name="Новый товар", price=Decimal("5.00"), stock=1)
        )

        # Setup
        after_count = await test_data.count_rows(tables.products, session)

        # Assert
        assert before_count + 1 == after_count
        assert isinstance(result, entities.Product)
        assert result.id is not None
