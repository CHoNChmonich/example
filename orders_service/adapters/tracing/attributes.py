"""Реестр имён атрибутов спанов проекта — по образцу ``opentelemetry.semconv.attributes``.

Все ключи в собственном пространстве ``orders_service.*``: пространства ``db.*``, ``http.*``,
``error.*`` зарезервированы семантическими конвенциями OpenTelemetry. Значения пишут владельцы
спанов (``span``, ``TracedUnitOfWork``, ``database.spans.TracedPool``); здесь только имена,
чтобы ключ нельзя было опечатать в двух местах и чтобы словарь атрибутов читался целиком.
"""

# Код ошибки ядра (``errors.Error.code``) на спане, завершившемся ожидаемым отказом сценария;
# статус такого спана не ERROR.
ERROR_CODE_ATTRIBUTE = "orders_service.error.code"

# Исход транзакции на спане ``unit_of_work``: ``committed`` либо ``rolled_back``.
OUTCOME_ATTRIBUTE = "orders_service.unit_of_work.outcome"

# Состояние пула соединений до взятия, на спане ``pool.connect``: размер пула, свободные и
# занятые соединения. ``overflow()`` SQLAlchemy не отдаётся: его счётчик стартует с
# отрицательного значения и сбивает читателя трассы.
POOL_SIZE_ATTRIBUTE = "orders_service.pool.size"
POOL_CHECKED_IN_ATTRIBUTE = "orders_service.pool.checked_in"
POOL_CHECKED_OUT_ATTRIBUTE = "orders_service.pool.checked_out"
