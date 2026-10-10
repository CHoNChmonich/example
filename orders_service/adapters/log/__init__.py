"""Конфигурация логирования — инфраструктура, а не адаптер порта.

Логирование — сквозная функциональность: любой слой берёт ``logging.getLogger(__name__)`` и
ничего не знает о хендлерах и форматах. Их задаёт этот пакет, а применяет composition root
(``configure``). Другие адаптеры могут использовать пакет как библиотеку (``request_id``),
обратных зависимостей у него нет.
"""

from .config import configure, make_config
from .context import RequestIdFilter, request_id
from .settings import Settings

__all__ = ["RequestIdFilter", "Settings", "configure", "make_config", "request_id"]
