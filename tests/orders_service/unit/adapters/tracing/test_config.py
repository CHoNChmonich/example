from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import (
    DEPLOYMENT_ENVIRONMENT,
    SERVICE_INSTANCE_ID,
    SERVICE_NAME,
    SERVICE_VERSION,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

from orders_service.adapters import tracing


# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
def _configure(**raw: str) -> TracerProvider:
    # Глобальный провайдер уже стоит из tests/conftest.py, повторную установку SDK игнорирует;
    # проверяется провайдер, который configure собрал и вернул
    return tracing.configure(tracing.Settings.model_validate(raw))


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestConfigure:
    def test__none_adds_no_processor(self) -> None:
        # Call
        provider = _configure()

        # Assert
        assert provider._active_span_processor._span_processors == ()

    def test__console_is_synchronous(self) -> None:
        # Call
        provider = _configure(TRACING_EXPORTER="console")

        # Assert: спан печатается сразу при завершении, не отставая от строк лога
        (processor,) = provider._active_span_processor._span_processors
        assert isinstance(processor, SimpleSpanProcessor)
        assert isinstance(processor.span_exporter, ConsoleSpanExporter)

    def test__otlp_is_batched_with_endpoint(self) -> None:
        # Call
        provider = _configure(
            TRACING_EXPORTER="otlp", TRACING_OTLP_ENDPOINT="http://collector:4318/v1/traces"
        )

        # Assert
        (processor,) = provider._active_span_processor._span_processors
        assert isinstance(processor, BatchSpanProcessor)
        assert isinstance(processor.span_exporter, OTLPSpanExporter)
        assert processor.span_exporter._endpoint == "http://collector:4318/v1/traces"
        provider.shutdown()

    def test__sampler_is_parent_based_ratio(self) -> None:
        # Call
        provider = _configure(TRACING_SAMPLE_RATIO="0.25")

        # Assert: корневой спан решает по доле, решение родителя наследуется
        sampler = provider.sampler
        assert isinstance(sampler, ParentBased)
        assert isinstance(sampler._root, TraceIdRatioBased)
        assert sampler._root.rate == 0.25

    def test__zero_ratio_keeps_trace_id_but_does_not_record(self) -> None:
        # Setup: нулевая доля — ни одна корневая трасса не записывается
        tracer = _configure(TRACING_SAMPLE_RATIO="0").get_tracer("test")

        # Call
        with tracer.start_as_current_span("root") as span:
            recording = span.is_recording()
            context = span.get_span_context()

        # Assert: спан не записан, но контекст с trace_id есть — логи корреляцию не теряют
        assert recording is False
        assert context.is_valid
        assert context.trace_flags.sampled is False

    def test__resource_describes_service(self) -> None:
        # Call
        provider = _configure(
            TRACING_SERVICE_NAME="orders-test",
            TRACING_SERVICE_VERSION="1.2.3",
            TRACING_ENVIRONMENT="staging",
            TRACING_SERVICE_INSTANCE_ID="orders-7f9c",
        )

        # Assert
        attributes = provider.resource.attributes
        assert attributes[SERVICE_NAME] == "orders-test"
        assert attributes[SERVICE_VERSION] == "1.2.3"
        assert attributes[DEPLOYMENT_ENVIRONMENT] == "staging"
        assert attributes[SERVICE_INSTANCE_ID] == "orders-7f9c"
