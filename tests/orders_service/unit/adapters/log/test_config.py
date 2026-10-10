from orders_service.adapters import log
from orders_service.adapters.log.config import JSON_FORMATTER


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestMakeConfig:
    def test__levels_become_propagating_loggers(self) -> None:
        # Setup
        settings = log.Settings.model_validate({"LOG_LEVEL": "warning"})

        # Call
        config = log.make_config(
            settings, {"sqlalchemy.engine": "INFO", "uvicorn.access": "NOTSET"}
        )

        # Assert
        assert config["root"] == {"level": "WARNING", "handlers": ["stdout"]}
        assert config["loggers"] == {
            "sqlalchemy.engine": {"level": "INFO", "handlers": [], "propagate": True},
            "uvicorn.access": {"level": "NOTSET", "handlers": [], "propagate": True},
        }
        assert config["disable_existing_loggers"] is False
        assert config["handlers"]["stdout"]["filters"] == ["request_id"]

    def test__text_formatter_by_default(self) -> None:
        # Call
        config = log.make_config(log.Settings.model_validate({}), {})

        # Assert
        formatter = config["formatters"]["default"]
        assert "class" not in formatter
        assert "%(request_id)s" in formatter["format"]

    def test__json_formatter(self) -> None:
        # Call
        config = log.make_config(log.Settings.model_validate({"LOG_FORMAT": "json"}), {})

        # Assert
        formatter = config["formatters"]["default"]
        assert formatter["()"] == JSON_FORMATTER
        assert formatter["json_ensure_ascii"] is False
        assert config["handlers"]["stdout"]["formatter"] == "default"
