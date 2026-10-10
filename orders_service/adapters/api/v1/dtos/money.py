"""Денежный тип ответов API.

Контракт API: деньги — строка с двумя знаками, независимо от того, прошло ли значение
через БД (``Numeric(…, 2)``) или только что посчитано в памяти (``Decimal("0")``).
"""

from decimal import Decimal
from typing import Annotated

from pydantic import PlainSerializer

Money = Annotated[Decimal, PlainSerializer(lambda value: f"{value:.2f}", return_type=str)]
