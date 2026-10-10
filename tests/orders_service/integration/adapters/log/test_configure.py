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
token = log.request_id.set("req-42")
logging.getLogger("uvicorn.access").info("access %%s", 200)
logging.getLogger("sqlalchemy.engine").info("скрыто уровнем")
log.request_id.reset(token)
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

        # Assert: ранний логгер пишет, uvicorn.access идёт в наш хендлер с id, WARNING режет SQL
        assert len(lines) == 2
        assert re.fullmatch(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} INFO     \[orders_service\.early\] \[-\] "
            r"запись до configure",
            lines[0],
        )
        assert re.fullmatch(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} INFO     \[uvicorn\.access\] \[req-42\] "
            r"access 200",
            lines[1],
        )

    def test__json_format(self) -> None:
        # Call
        lines = _run("json")
        records = [json.loads(line) for line in lines]

        # Assert
        assert [record["name"] for record in records] == ["orders_service.early", "uvicorn.access"]
        assert records[0]["request_id"] == "-"
        assert records[1]["request_id"] == "req-42"
        assert records[1]["levelname"] == "INFO"
        assert records[1]["message"] == "access 200"
        assert "asctime" in records[1]
        assert "запись до configure" in lines[0]  # кириллица не экранирована

    @pytest.mark.parametrize("log_format", ["text", "json"])
    def test__exactly_two_lines(self, log_format: str) -> None:
        # Call and Assert: без дублей от собственных хендлеров сторонних логгеров
        assert len(_run(log_format)) == 2
