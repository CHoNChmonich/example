import asyncio
from unittest.mock import ANY, MagicMock, Mock

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from orders_service.adapters import tracing
from orders_service.application import errors, interfaces


# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
@pytest.fixture(scope="function")
def inner() -> MagicMock:
    unit_of_work = MagicMock(spec=interfaces.UnitOfWork)
    unit_of_work.__aenter__.return_value = unit_of_work
    unit_of_work.customers = Mock(interfaces.CustomersRepo)
    unit_of_work.products = Mock(interfaces.ProductsRepo)
    unit_of_work.orders = Mock(interfaces.OrdersRepo)
    return unit_of_work


@pytest.fixture(scope="function")
def uow(inner: MagicMock) -> tracing.TracedUnitOfWork:
    return tracing.TracedUnitOfWork(inner)


def _single(spans: InMemorySpanExporter) -> ReadableSpan:
    (span,) = spans.get_finished_spans()
    assert span.name == "unit_of_work"
    return span


def _outcome(span: ReadableSpan) -> object:
    assert span.attributes is not None
    return span.attributes[tracing.OUTCOME_ATTRIBUTE]


def _exception_types(span: ReadableSpan) -> list[str]:
    types: list[str] = []
    for event in span.events:
        assert event.attributes is not None
        types.append(str(event.attributes["exception.type"]))
    return types


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestEnter:
    async def test__returns_decorator_and_delegates_repositories(
        self, uow: tracing.TracedUnitOfWork, inner: MagicMock, spans: InMemorySpanExporter
    ) -> None:
        # Call
        async with uow as entered:
            current = trace.get_current_span()
            repositories = (entered.customers, entered.products, entered.orders)

        # Assert: commit сервиса пойдёт через декоратор; репозитории — внутреннего UoW
        assert entered is uow
        assert repositories == (inner.customers, inner.products, inner.orders)
        assert current.get_span_context().is_valid
        inner.__aenter__.assert_awaited_once()
        assert _outcome(_single(spans)) == "rolled_back"
        assert not trace.get_current_span().get_span_context().is_valid

    async def test__inner_failure_closes_span(
        self, uow: tracing.TracedUnitOfWork, inner: MagicMock, spans: InMemorySpanExporter
    ) -> None:
        # Setup
        inner.__aenter__.side_effect = RuntimeError("нет сессии")

        # Call
        with pytest.raises(RuntimeError):
            async with uow:
                pass

        # Assert: спан закрыт с ошибкой, выход внутреннего не вызывался, состояния не осталось
        span = _single(spans)
        assert span.status.status_code is StatusCode.ERROR
        assert _exception_types(span) == ["RuntimeError"]
        inner.__aexit__.assert_not_called()
        assert not hasattr(uow, "_scope")
        assert not trace.get_current_span().get_span_context().is_valid

    async def test__nested_enter_keeps_outer_intact(
        self, uow: tracing.TracedUnitOfWork, inner: MagicMock, spans: InMemorySpanExporter
    ) -> None:
        # Setup: внутренний UoW отвечает на вложенный вход RuntimeError, как database.UnitOfWork
        inner.__aenter__.side_effect = [inner, RuntimeError("уже открыт")]

        # Call
        async with uow:
            with pytest.raises(RuntimeError):
                async with uow:
                    pass
            await uow.commit()

        # Assert: внешний объект остался рабочим; два спана — вложенный с ошибкой, внешний нет
        nested, outer = spans.get_finished_spans()
        assert nested.status.status_code is StatusCode.ERROR
        assert outer.status.status_code is StatusCode.UNSET
        assert _outcome(outer) == "committed"
        assert not trace.get_current_span().get_span_context().is_valid

    async def test__sequential_reuse(
        self, uow: tracing.TracedUnitOfWork, spans: InMemorySpanExporter
    ) -> None:
        # Call
        async with uow:
            pass
        async with uow:
            pass

        # Assert
        assert [span.name for span in spans.get_finished_spans()] == ["unit_of_work"] * 2


class TestCommit:
    async def test__delegates_and_marks_outcome(
        self, uow: tracing.TracedUnitOfWork, inner: MagicMock, spans: InMemorySpanExporter
    ) -> None:
        # Call
        async with uow:
            await uow.commit()

        # Assert
        inner.commit.assert_awaited_once_with()
        assert _outcome(_single(spans)) == "committed"


class TestExit:
    async def test__passes_body_exception_to_inner(
        self, uow: tracing.TracedUnitOfWork, inner: MagicMock, spans: InMemorySpanExporter
    ) -> None:
        # Setup
        error = ValueError("сбой сценария")

        # Call
        with pytest.raises(ValueError) as excinfo:
            async with uow:
                raise error

        # Assert: внутренний получил то же исключение, наружу вышло оно же, спан — ERROR
        inner.__aexit__.assert_awaited_once_with(ValueError, error, ANY)
        assert excinfo.value is error
        span = _single(spans)
        assert _outcome(span) == "rolled_back"
        assert span.status.status_code is StatusCode.ERROR
        assert _exception_types(span) == ["ValueError"]
        assert not trace.get_current_span().get_span_context().is_valid

    async def test__domain_error_is_not_a_span_error(
        self, uow: tracing.TracedUnitOfWork, spans: InMemorySpanExporter
    ) -> None:
        # Call
        with pytest.raises(errors.OrderNotFound):
            async with uow:
                raise errors.OrderNotFound(id=1)

        # Assert
        span = _single(spans)
        assert _outcome(span) == "rolled_back"
        assert span.status.status_code is StatusCode.UNSET
        assert span.attributes is not None
        assert span.attributes[tracing.ERROR_CODE_ATTRIBUTE] == "order_not_found"
        assert span.events == ()

    async def test__cancellation(
        self, uow: tracing.TracedUnitOfWork, inner: MagicMock, spans: InMemorySpanExporter
    ) -> None:
        # Call
        with pytest.raises(asyncio.CancelledError):
            async with uow:
                raise asyncio.CancelledError()

        # Assert: отмена дошла до внутреннего UoW, спан завершён без ошибки, контекст снят
        inner.__aexit__.assert_awaited_once_with(asyncio.CancelledError, ANY, ANY)
        span = _single(spans)
        assert span.status.status_code is StatusCode.UNSET
        assert not trace.get_current_span().get_span_context().is_valid

    async def test__inner_replaces_exception_with_storage_unavailable(
        self, uow: tracing.TracedUnitOfWork, inner: MagicMock, spans: InMemorySpanExporter
    ) -> None:
        # Setup: как database.UnitOfWork — сбой хранилища заменён ошибкой ядра с причиной
        replacement = errors.StorageUnavailable()
        replacement.__cause__ = ConnectionError("обрыв")
        inner.__aexit__.side_effect = replacement

        # Call
        with pytest.raises(errors.StorageUnavailable) as excinfo:
            async with uow:
                raise ConnectionError("обрыв")

        # Assert: наружу — замена, в спане — исходный сбой
        assert excinfo.value is replacement
        span = _single(spans)
        assert _outcome(span) == "rolled_back"
        assert span.status.status_code is StatusCode.ERROR
        assert _exception_types(span) == ["ConnectionError"]
        assert not trace.get_current_span().get_span_context().is_valid

    async def test__inner_exit_failure(
        self, uow: tracing.TracedUnitOfWork, inner: MagicMock, spans: InMemorySpanExporter
    ) -> None:
        # Setup: сбой отката, не признанный временным, приходит как есть
        inner.__aexit__.side_effect = RuntimeError("откат не удался")

        # Call
        with pytest.raises(RuntimeError):
            async with uow:
                pass

        # Assert
        span = _single(spans)
        assert span.status.status_code is StatusCode.ERROR
        assert _exception_types(span) == ["RuntimeError"]
        assert not hasattr(uow, "_scope")
        assert not trace.get_current_span().get_span_context().is_valid
