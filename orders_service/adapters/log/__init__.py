"""Конфигурация логирования — инфраструктура, а не адаптер порта.

Логирование — сквозная функциональность: любой слой берёт ``logging.getLogger(__name__)`` и
ничего не знает о хендлерах и форматах. Их задаёт этот пакет, а применяет composition root
(``configure``); сборка словаря ``dictConfig`` — деталь модуля ``config``. Зависимостей на
другие адаптеры у пакета нет; идентификаторы трассы фильтр читает у фасада
``opentelemetry.trace``, не у адаптера трассировки.
"""

from .config import configure
from .context import LogContextFilter
from .settings import Settings

__all__ = ["LogContextFilter", "Settings", "configure"]
