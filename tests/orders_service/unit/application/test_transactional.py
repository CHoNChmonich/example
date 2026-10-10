from unittest.mock import ANY, MagicMock, Mock, call

import pytest

from orders_service.application import interfaces
from orders_service.application.transactional import transactional


# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
@pytest.fixture(scope="function")
def uow() -> MagicMock:
    unit_of_work = MagicMock(spec=interfaces.UnitOfWork)
    unit_of_work.__aenter__.return_value = unit_of_work
    return unit_of_work


@pytest.fixture(scope="function")
def uow_factory(uow: MagicMock) -> Mock:
    factory = Mock(interfaces.UnitOfWorkFactory)
    factory.create.return_value = uow
    return factory


class _Service:
    """Игрушечный сервис: ровно то, что обёртка требует от настоящего."""

    def __init__(self, uow_factory: interfaces.UnitOfWorkFactory) -> None:
        self.uow_factory = uow_factory

    @transactional
    async def run(
        self, uow: interfaces.UnitOfWork, value: int
    ) -> tuple[interfaces.UnitOfWork, int]:
        return uow, value * 2

    @transactional
    async def fail(self, uow: interfaces.UnitOfWork, error: Exception) -> None:
        raise error


@pytest.fixture(scope="function")
def service(uow_factory: Mock) -> _Service:
    return _Service(uow_factory)


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestTransactional:
    async def test__passes_fresh_uow_and_commits(self, service: _Service, uow: MagicMock) -> None:
        # Call
        received_uow, result = await service.run(2)

        # Assert
        assert received_uow is uow
        assert result == 4
        assert uow.mock_calls == [
            call.__aenter__(),
            call.commit(),
            call.__aexit__(None, None, None),
        ]

    async def test__exception_skips_commit_and_propagates(
        self, service: _Service, uow: MagicMock
    ) -> None:
        # Setup
        error = RuntimeError("boom")

        # Call and Assert
        with pytest.raises(RuntimeError) as exc_info:
            await service.fail(error)

        assert exc_info.value is error
        uow.commit.assert_not_called()
        uow.__aexit__.assert_called_once_with(RuntimeError, error, ANY)

    async def test__commit_failure_propagates_through_aexit(
        self, service: _Service, uow: MagicMock
    ) -> None:
        # Setup
        error = RuntimeError("commit failed")
        uow.commit.side_effect = error

        # Call and Assert
        with pytest.raises(RuntimeError) as exc_info:
            await service.run(1)

        assert exc_info.value is error
        uow.__aexit__.assert_called_once_with(RuntimeError, error, ANY)

    async def test__new_unit_of_work_per_call(self, service: _Service, uow_factory: Mock) -> None:
        # Call
        await service.run(1)
        await service.run(2)

        # Assert
        assert uow_factory.create.call_count == 2
