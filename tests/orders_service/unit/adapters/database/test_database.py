import pytest

from orders_service.adapters import database


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestLoggerLevels:
    @pytest.mark.parametrize("echo, level", [(True, "INFO"), (False, "WARNING")])
    def test__sql_level_by_echo_flag(self, echo: bool, level: str) -> None:
        # Setup
        settings = database.Settings.model_validate(
            {
                "POSTGRES_USER": "orders",
                "POSTGRES_PASSWORD": "orders",
                "POSTGRES_DB": "orders",
                "POSTGRES_ECHO_SQL": echo,
            }
        )

        # Call and Assert
        assert database.logger_levels(settings) == {"sqlalchemy.engine": level}
