"""Ошибки приложения.

Иерархия: ``Error`` → категория (``NotFoundError``, ``ConflictError``, ``RuleViolationError``,
``StorageUnavailable``) → конкретная ошибка. Код ошибки выводится из имени класса
(``CustomerNotFound`` → ``customer_not_found``), текст — из ``message_template`` и контекста,
переданного именованными аргументами. Адаптеры отображают на свои коды именно категории
(HTTP-адаптер: 404 / 409 / 400 / 503), поэтому новая ошибка не требует правок адаптеров.
"""

import re
from typing import ClassVar

_CAMEL_CASE_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


class Error(Exception):
    """Базовая ошибка логики приложения.

    Attributes:
        message_template: Шаблон текста ошибки; подстановки берутся из контекста.
        code: Машинный код ошибки в snake_case; по умолчанию выводится из имени класса.
        context: Именованные значения, с которыми ошибка была поднята (попадают в ответ API).
        message: Готовый текст ошибки для человека.
    """

    message_template: ClassVar[str] = "Ошибка приложения"
    code: ClassVar[str] = "error"

    def __init_subclass__(cls) -> None:
        """Выводит код ошибки из имени класса-наследника, если он не задан явно."""
        super().__init_subclass__()
        if "code" not in cls.__dict__:
            cls.code = _CAMEL_CASE_BOUNDARY.sub("_", cls.__name__).lower()

    def __init__(self, **context: object) -> None:
        """Собирает текст ошибки из шаблона и контекста.

        Args:
            **context: Значения для подстановки в ``message_template``; сохраняются
                в ``context`` и уходят клиенту в теле ответа.
        """
        self.context = context
        self.message = self.message_template.format_map(context)
        super().__init__(self.message)


class NotFoundError(Error):
    """Категория: запрошенная сущность не найдена."""


class ConflictError(Error):
    """Категория: запрос конфликтует с текущим состоянием данных."""


class RuleViolationError(Error):
    """Категория: нарушено бизнес-правило."""


class StorageUnavailable(Error):
    """Категория из одного класса: хранилище временно недоступно или транзакция прервана.

    Обрыв соединения, дедлок, сбой сериализации; повтор запроса может помочь.
    """

    message_template = "Хранилище временно недоступно, повторите попытку"


class CustomerNotFound(NotFoundError):
    """Клиент с указанным ``id`` отсутствует."""

    message_template = "Клиент с id {id} не найден"


class CustomerAlreadyExists(ConflictError):
    """Клиент с таким ``email`` уже зарегистрирован."""

    message_template = "Клиент с email {email} уже существует"


class ProductNotFound(NotFoundError):
    """Товар с указанным ``id`` отсутствует."""

    message_template = "Товар с id {id} не найден"


class OrderNotFound(NotFoundError):
    """Заказ с указанным ``id`` отсутствует."""

    message_template = "Заказ с id {id} не найден"


class InsufficientStock(RuleViolationError):
    """Остатка товара не хватает на запрошенное количество."""

    message_template = (
        "Товара {product_id} недостаточно: запрошено {requested}, доступно {available}"
    )


class OrderTransitionNotAllowed(RuleViolationError):
    """Действие недопустимо в текущем статусе заказа."""

    message_template = "Заказ {id} в статусе {status}: действие «{action}» недопустимо"
