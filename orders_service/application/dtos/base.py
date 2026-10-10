"""Общие ограничения полей DTO: границы входа совпадают с границами хранилища.

Те же типы использует HTTP-шов (``adapters/api/v1/schemas``): тело запроса, прошедшее
валидацию на границе, гарантированно принимается ядром, а вход, который хранилище
не вместит, отклоняется как 400, а не падает в 500 на запросе к БД.
"""

from decimal import Decimal
from typing import Annotated

from pydantic import Field, StringConstraints

MAX_INT32 = 2**31 - 1  # колонки Integer (int4) в PostgreSQL
MAX_LINE_QUANTITY = 1_000_000  # единиц одного товара в строке заказа
MAX_ORDER_LINES = 100  # строк в заказе; с ценой и количеством не переполняет Numeric(20, 2)
MAX_PAGE_LIMIT = 200

# Email только из ASCII: приведение к нижнему регистру не меняет длину строки, тогда как
# проверка длины в pydantic идёт до нормализации (для «İ» lower() даёт два символа).
_EMAIL_PATTERN = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$"

EntityId = Annotated[int, Field(ge=1, le=MAX_INT32)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Email = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True, max_length=255, pattern=_EMAIL_PATTERN),
]
Price = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
Stock = Annotated[int, Field(ge=0, le=MAX_INT32)]
Quantity = Annotated[int, Field(ge=1, le=MAX_LINE_QUANTITY)]
# OFFSET в запросе — bigint, но смещение дальше int4 смысла не имеет и в БД не уходит.
Offset = Annotated[int, Field(ge=0, le=MAX_INT32)]
