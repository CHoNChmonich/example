"""``configure`` меняет глобальное состояние ``logging``, поэтому проверяется в дочернем процессе:
``caplog`` и хендлеры pytest остаются нетронутыми."""

import json
import os
import re
import subprocess
import sys

import pytest

# ---------------------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------------------
SCRIPT = """
import logging
from orders_service.adapters import log

early = logging.getLogger("orders_service.early")  # создан до configure
settings = log.Settings.model_validate({"LOG_LEVEL": "INFO", "LOG_FORMAT": "%s"})
log.configure(settings, levels={"uvicorn.access": "NOTSET", "sqlalchemy.engine": "WARNING"})
early.info("запись до configure")
from opentelemetry.sdk.trace import TracerProvider
with TracerProvider().get_tracer("test").start_as_current_span("span"):
    logging.getLogger("uvicorn.access").info("access %%s", 200)
    logging.getLogger("sqlalchemy.engine").info("скрыто уровнем")
logging.getLogger("orders_service.after").info("вне спана")
"""


def _run(log_format: str) -> list[str]:
    result = subprocess.run(  # noqa: S603 — запускается свой интерпретатор с собственным скриптом
        [sys.executable, "-c", SCRIPT % log_format],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=True,
    )
    return result.stdout.strip().splitlines()


# ---------------------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------------------
class TestConfigure:
    def test__text_format(self) -> None:
        # Call
        lines = _run("text")

        # Assert: ранний логгер пишет, uvicorn.access идёт в наш хендлер с trace_id спана,
        # WARNING режет SQL, вне спана — прочерк
        assert len(lines) == 3
        assert re.fullmatch(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} INFO     \[orders_service\.early\] \[-\] "
            r"запись до configure",
            lines[0],
        )
        assert re.fullmatch(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} INFO     \[uvicorn\.access\] \[[0-9a-f]{32}\] "
            r"access 200",
            lines[1],
        )
        assert re.fullmatch(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} INFO     \[orders_service\.after\] \[-\] "
            r"вне спана",
            lines[2],
        )

    def test__json_format(self) -> None:
        # Call
        lines = _run("json")
        records = [json.loads(line) for line in lines]

        # Assert
        assert [record["name"] for record in records] == [
            "orders_service.early",
            "uvicorn.access",
            "orders_service.after",
        ]
        assert records[1]["levelname"] == "INFO"
        assert records[1]["message"] == "access 200"
        assert "asctime" in records[1]
        assert "запись до configure" in lines[0]  # кириллица не экранирована
        assert records[0]["trace_id"] == "-"
        assert re.fullmatch(r"[0-9a-f]{32}", records[1]["trace_id"])
        assert re.fullmatch(r"[0-9a-f]{16}", records[1]["span_id"])
        assert records[2]["trace_id"] == "-"

    @pytest.mark.parametrize("log_format", ["text", "json"])
    def test__exactly_three_lines(self, log_format: str) -> None:
        # Call and Assert: без дублей от собственных хендлеров сторонних логгеров
        assert len(_run(log_format)) == 3
