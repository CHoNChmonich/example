import importlib
from types import ModuleType

import pytest

from orders_service.adapters import database


# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
@pytest.fixture(scope="function")
def launcher(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    # Composition root читает настройки при импорте; соединение с БД при этом не открывается
    monkeypatch.setenv("POSTGRES_USER", "orders")
    monkeypatch.setenv("POSTGRES_PASSWORD", "orders")
    monkeypatch.setenv("POSTGRES_DB", "orders")
    return importlib.import_module("orders_service.launchers.api")


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestAdapters:
    async def test__uow_factory_builds_unit_of_work(self, launcher: ModuleType) -> None:
        # Call: вход и выход без запросов — partial собран с нужными аргументами
        async with launcher.Adapters.uow_factory() as uow:
            # Assert
            assert isinstance(uow, database.UnitOfWork)


class TestApplication:
    def test__services_share_uow_factory(self, launcher: ModuleType) -> None:
        # Assert
        assert launcher.Application.customer.uow_factory is launcher.Adapters.uow_factory
        assert launcher.Application.product.uow_factory is launcher.Adapters.uow_factory
        assert launcher.Application.order.uow_factory is launcher.Adapters.uow_factory
