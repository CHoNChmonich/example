"""Трассировка OpenTelemetry: конфигурация SDK и декораторы, создающие спаны.

Две части. Конфигурация (``Settings``, ``configure``, ``shutdown``) знает только SDK:
``configure`` собирает провайдер — ресурс (сервис, версия, окружение, экземпляр), сэмплер по
доле трасс, процессор и экспортёр по настройкам — и ставит его глобально; сборщики — детали
модуля ``config``. Обёртки (``TracedUnitOfWork`` над портом ``interfaces.UnitOfWork``,
``TracedCustomer``/``TracedProduct``/``TracedOrder`` над входящими портами) реализуют порты
ядра и добавляют спаны по паттерну Decorator; их собирает composition root, ядро,
``database.UnitOfWork`` и ``Database`` о трассировке не знают. Политика исхода спана — в
``span``, её используют все обёртки, включая ``database.spans.TracedPool`` (тот импортирует
этот пакет как библиотеку; обратных импортов нет). HTTP-спан запроса даёт встроенная
телеметрия FastAPI, SQL-спаны — слушатели ``database.spans``. Без настроенного провайдера
фасад отдаёт no-op спаны.
"""

from .attributes import (
    ERROR_CODE_ATTRIBUTE,
    OUTCOME_ATTRIBUTE,
    POOL_CHECKED_IN_ATTRIBUTE,
    POOL_CHECKED_OUT_ATTRIBUTE,
    POOL_SIZE_ATTRIBUTE,
)
from .config import configure, shutdown
from .services import TracedCustomer, TracedOrder, TracedProduct
from .settings import Settings
from .spans import span
from .unit_of_work import TracedUnitOfWork

__all__ = [
    "ERROR_CODE_ATTRIBUTE",
    "OUTCOME_ATTRIBUTE",
    "POOL_CHECKED_IN_ATTRIBUTE",
    "POOL_CHECKED_OUT_ATTRIBUTE",
    "POOL_SIZE_ATTRIBUTE",
    "Settings",
    "TracedCustomer",
    "TracedOrder",
    "TracedProduct",
    "TracedUnitOfWork",
    "configure",
    "shutdown",
    "span",
]
