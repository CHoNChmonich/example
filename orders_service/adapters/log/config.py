"""Конфигурация ``logging``: один хендлер в stdout, формат по настройкам, фильтр request id."""

import logging.config
from collections.abc import Mapping
from typing import Any

from .context import RequestIdFilter
from .settings import Settings

JSON_FORMATTER = "pythonjsonlogger.json.JsonFormatter"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_TEXT_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] [%(request_id)s] %(message)s"
_JSON_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def make_config(settings: Settings, levels: Mapping[str, str]) -> dict[str, Any]:
    """Собирает dictConfig: хендлер в stdout, форматтер по ``LOG_FORMAT``, фильтр request id.

    Логгеры из ``levels`` получают уровень, лишаются собственных хендлеров и уходят в корень
    (``propagate``): так сторонние библиотеки пишут нашим форматом; ``NOTSET`` означает
    «наследовать уровень корня». Ранее созданные логгеры не отключаются. JSON-форматтер
    добавляет ``request_id`` сам (python-json-logger включает в объект нестандартные
    атрибуты записи) и не экранирует кириллицу — сырой лог остаётся читаемым.

    Args:
        settings: Уровень и формат.
        levels: Уровни сторонних логгеров по имени.

    Returns:
        Словарь для ``logging.config.dictConfig``.
    """
    formatter: dict[str, Any] = (
        {"()": JSON_FORMATTER, "fmt": _JSON_FORMAT, "json_ensure_ascii": False}
        if settings.LOG_FORMAT == "json"
        else {"format": _TEXT_FORMAT}
    )
    formatter["datefmt"] = _DATE_FORMAT
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"request_id": {"()": RequestIdFilter}},
        "formatters": {"default": formatter},
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "default",
                "filters": ["request_id"],
            }
        },
        "root": {"level": settings.LOG_LEVEL, "handlers": ["stdout"]},
        "loggers": {
            name: {"level": level, "handlers": [], "propagate": True}
            for name, level in levels.items()
        },
    }


def configure(settings: Settings, *, levels: Mapping[str, str]) -> None:
    """Применяет конфигурацию к ``logging`` процесса.

    Args:
        settings: Уровень и формат.
        levels: Уровни сторонних логгеров по имени (см. ``make_config``).
    """
    logging.config.dictConfig(make_config(settings, levels))
