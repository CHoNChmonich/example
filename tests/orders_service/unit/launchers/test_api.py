import importlib
from types import ModuleType

import pytest

from orders_service.adapters import database, tracing


# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
@pytest.fixture(scope="function")
def launcher(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    # Composition root читает настройки при импорте; соединение с БД при этом не открывается
    monkeypatch.setenv("POSTGRES_USER", "orders")
    monkeypatch.setenv("POSTGRES_PASSWORD", "orders")
    monkeypatch.setenv("POSTGRES_DB", "orders")
    monkeypatch.setenv("TRACING_EXPORTER", "none")  # без экспорта и его остановки
    return importlib.import_module("orders_service.launchers.api")


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestAdapters:
    async def test__uow_factory_builds_traced_unit_of_work(self, launcher: ModuleType) -> None:
        # Call: вход и выход без запросов — декоратор над настоящим UoW адаптера БД
        async with launcher.Adapters.uow_factory() as uow:
            # Assert
            assert isinstance(uow, tracing.TracedUnitOfWork)
            assert isinstance(uow.customers, database.repositories.CustomersRepo)

    def test__engine_uses_traced_pool(self, launcher: ModuleType) -> None:
        # Assert
        assert isinstance(launcher.Adapters.db.engine.pool, database.spans.TracedPool)


class TestApplication:
    def test__services_share_uow_factory(self, launcher: ModuleType) -> None:
        # Assert
        assert launcher.Application.customer.uow_factory is launcher.Adapters.uow_factory
        assert launcher.Application.product.uow_factory is launcher.Adapters.uow_factory
        assert launcher.Application.order.uow_factory is launcher.Adapters.uow_factory


class TestControllers:
    def test__controller_gets_decorated_services(self, launcher: ModuleType) -> None:
        # Assert
        controller = launcher.Controllers.v1_controller
        assert controller.customer is launcher.Decorators.customer
        assert controller.product is launcher.Decorators.product
        assert controller.order is launcher.Decorators.order
