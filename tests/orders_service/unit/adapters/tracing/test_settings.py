import socket
from importlib.metadata import version

import pytest
from pydantic import ValidationError

from orders_service.adapters import tracing


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestSettings:
    def test__defaults(self) -> None:
        # Call
        settings = tracing.Settings.model_validate({})

        # Assert
        assert settings.TRACING_EXPORTER == "none"
        assert settings.TRACING_OTLP_ENDPOINT == "http://localhost:4318/v1/traces"
        assert settings.TRACING_SAMPLE_RATIO == 1.0
        assert settings.TRACING_SERVICE_NAME == "orders-service"
        assert settings.TRACING_SERVICE_VERSION == version("orders-service")
        assert settings.TRACING_ENVIRONMENT == "development"
        assert settings.TRACING_SERVICE_INSTANCE_ID == socket.gethostname()

    @pytest.mark.parametrize("raw", ["jaeger", "", "CONSOLE"])
    def test__unknown_exporter_rejected(self, raw: str) -> None:
        # Call and Assert
        with pytest.raises(ValidationError):
            tracing.Settings.model_validate({"TRACING_EXPORTER": raw})

    @pytest.mark.parametrize("raw", ["0", "0.25", "1"])
    def test__sample_ratio_within_bounds(self, raw: str) -> None:
        # Call
        settings = tracing.Settings.model_validate({"TRACING_SAMPLE_RATIO": raw})

        # Assert
        assert settings.TRACING_SAMPLE_RATIO == float(raw)

    @pytest.mark.parametrize("raw", ["-0.1", "1.5", "all"])
    def test__sample_ratio_out_of_bounds_rejected(self, raw: str) -> None:
        # Call and Assert
        with pytest.raises(ValidationError):
            tracing.Settings.model_validate({"TRACING_SAMPLE_RATIO": raw})

    def test__resource_fields_overridable(self) -> None:
        # Call
        settings = tracing.Settings.model_validate(
            {
                "TRACING_SERVICE_VERSION": "1.2.3",
                "TRACING_ENVIRONMENT": "production",
                "TRACING_SERVICE_INSTANCE_ID": "orders-7f9c",
            }
        )

        # Assert
        assert settings.TRACING_SERVICE_VERSION == "1.2.3"
        assert settings.TRACING_ENVIRONMENT == "production"
        assert settings.TRACING_SERVICE_INSTANCE_ID == "orders-7f9c"
