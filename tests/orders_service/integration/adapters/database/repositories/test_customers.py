import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orders_service.adapters.database import repositories, tables
from orders_service.application import entities, errors

from .. import test_data


# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
@pytest.fixture(scope="function", autouse=True)
async def fill_db(session: AsyncSession) -> dict[str, list[int]]:
    customer_ids: list[int] = await test_data.insert_customers(session)
    return {"customer_ids": customer_ids}


@pytest.fixture(scope="function")
def repo(session: AsyncSession) -> repositories.CustomersRepo:
    return repositories.CustomersRepo(session)


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestFetchById:
    async def test__fetch_by_id(
        self, repo: repositories.CustomersRepo, fill_db: dict[str, list[int]]
    ) -> None:
        # Setup
        customer_id: int = fill_db["customer_ids"][0]

        # Call
        result = await repo.fetch_by_id(customer_id)

        # Assert
        assert isinstance(result, entities.Customer)
        assert result.id == customer_id
        assert result.email == test_data.CUSTOMERS_DATA[0]["email"]

    async def test__customer_not_found(
        self, repo: repositories.CustomersRepo, fill_db: dict[str, list[int]]
    ) -> None:
        # Setup
        missing_id: int = max(fill_db["customer_ids"]) + 1

        # Call
        result = await repo.fetch_by_id(missing_id)

        # Assert
        assert result is None


class TestFetchByEmail:
    async def test__fetch_by_email(
        self, repo: repositories.CustomersRepo, fill_db: dict[str, list[int]]
    ) -> None:
        # Setup
        email: str = str(test_data.CUSTOMERS_DATA[1]["email"])

        # Call
        result = await repo.fetch_by_email(email)

        # Assert
        assert isinstance(result, entities.Customer)
        assert result.id == fill_db["customer_ids"][1]
        assert result.email == email

    async def test__customer_not_found(self, repo: repositories.CustomersRepo) -> None:
        # Call
        result = await repo.fetch_by_email("nobody@example.com")

        # Assert
        assert result is None


class TestAdd:
    async def test__add(self, repo: repositories.CustomersRepo, session: AsyncSession) -> None:
        # Setup
        before_count = await test_data.count_rows(tables.customers, session)

        # Call
        result = await repo.add(entities.Customer(name="Новый клиент", email="new@example.com"))

        # Setup
        after_count = await test_data.count_rows(tables.customers, session)

        # Assert
        assert before_count + 1 == after_count
        assert isinstance(result, entities.Customer)
        assert result.id is not None

    async def test__email_already_exists(self, repo: repositories.CustomersRepo) -> None:
        # Setup
        taken_email: str = str(test_data.CUSTOMERS_DATA[0]["email"])

        # Call and Assert
        with pytest.raises(errors.CustomerAlreadyExists) as exc_info:
            await repo.add(entities.Customer(name="Двойник", email=taken_email))

        assert exc_info.value.context == {"email": taken_email}
