import pytest
from pydantic import ValidationError

from orders_service.adapters import log


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestSettings:
    @pytest.mark.parametrize(
        "raw, expected", [("debug", "DEBUG"), ("Warning", "WARNING"), ("INFO", "INFO")]
    )
    def test__level_uppercased(self, raw: str, expected: str) -> None:
        # Call
        settings = log.Settings.model_validate({"LOG_LEVEL": raw})

        # Assert
        assert settings.LOG_LEVEL == expected

    @pytest.mark.parametrize("raw", ["TRACE", "VERBOSE", ""])
    def test__unknown_level_rejected(self, raw: str) -> None:
        # Call and Assert
        with pytest.raises(ValidationError):
            log.Settings.model_validate({"LOG_LEVEL": raw})

    def test__defaults(self) -> None:
        # Call
        settings = log.Settings.model_validate({})

        # Assert
        assert settings.LOG_LEVEL == "INFO"
        assert settings.LOG_FORMAT == "text"
