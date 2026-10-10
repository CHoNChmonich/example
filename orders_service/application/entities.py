"""Domain слой: перечисления, политики скидок (Strategy), состояния заказа (State), сущности.

Сущности — dataclass'ы с тем поведением, которое принадлежит им самим: резерв остатка,
применение скидки, переходы статуса. Персистентность о сущностях знает только через
императивный маппинг в ``adapters/database/mapping.py``; сюда SQLAlchemy не проникает.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from orders_service.application import errors

_MONEY_STEP = Decimal("0.01")


class OrderStatus(StrEnum):
    """Статус заказа; в БД хранится значение члена (``new``, ``paid``, ``cancelled``)."""

    NEW = "new"
    PAID = "paid"
    CANCELLED = "cancelled"


# --- Политики скидок ------------------------------------------------------------------


class DiscountPolicy(ABC):
    """Паттерн: Strategy (GoF). Правило расчёта скидки на заказ.

    Контекст — ``Order.apply_discount``; конкретную политику выбирает composition root
    (``launchers/api.py``), сервис заказов знает только абстракцию.
    """

    @abstractmethod
    def discount_for(self, subtotal: Decimal, total_quantity: int) -> Decimal:
        """Рассчитывает сумму скидки на заказ.

        Args:
            subtotal: Сумма заказа до скидки.
            total_quantity: Общее количество единиц товара в заказе.

        Returns:
            Сумма скидки в тех же единицах, что и ``subtotal``.
        """


class NoDiscount(DiscountPolicy):
    """Паттерн: Null Object. Скидки нет — ноль вместо проверки «а есть ли политика»."""

    def discount_for(self, subtotal: Decimal, total_quantity: int) -> Decimal:
        """Возвращает нулевую скидку при любом заказе.

        Args:
            subtotal: Сумма заказа до скидки; не используется.
            total_quantity: Общее количество единиц; не используется.

        Returns:
            Ноль.
        """
        return Decimal("0")


class VolumeDiscount(DiscountPolicy):
    """Объёмная скидка: процент от суммы при общем количестве единиц не ниже порога.

    Attributes:
        min_quantity: Порог количества единиц, с которого (включительно) действует скидка.
        percent: Размер скидки в процентах от суммы заказа.
    """

    def __init__(self, *, min_quantity: int, percent: Decimal) -> None:
        """Задаёт параметры скидки.

        Args:
            min_quantity: Порог количества единиц, порог включительно.
            percent: Процент от суммы заказа.
        """
        self.min_quantity = min_quantity
        self.percent = percent

    def discount_for(self, subtotal: Decimal, total_quantity: int) -> Decimal:
        """Считает скидку, округляя до копеек по правилу «половина вверх».

        Args:
            subtotal: Сумма заказа до скидки.
            total_quantity: Общее количество единиц товара в заказе.

        Returns:
            ``percent`` процентов от ``subtotal``, если ``total_quantity`` не ниже порога,
            иначе ноль.
        """
        if total_quantity < self.min_quantity:
            return Decimal("0")
        return (subtotal * self.percent / 100).quantize(_MONEY_STEP, rounding=ROUND_HALF_UP)


# --- Состояния заказа -----------------------------------------------------------------


class _OrderState(ABC):
    """Паттерн: State (GoF). Поведение заказа, зависящее от его статуса.

    ``Order.pay`` / ``Order.cancel`` делегируют объекту состояния; недопустимый переход —
    ``OrderTransitionNotAllowed``. Новый статус = новый класс состояния + строка в ``_STATES``.
    """

    @abstractmethod
    def pay(self, order: Order) -> None:
        """Переводит заказ в статус «оплачен».

        Args:
            order: Заказ, статус которого меняется.

        Raises:
            OrderTransitionNotAllowed: Из этого состояния оплата невозможна.
        """

    @abstractmethod
    def cancel(self, order: Order) -> None:
        """Переводит заказ в статус «отменён».

        Args:
            order: Заказ, статус которого меняется.

        Raises:
            OrderTransitionNotAllowed: Из этого состояния отмена невозможна.
        """


class _NewOrderState(_OrderState):
    """Новый заказ: можно оплатить или отменить."""

    def pay(self, order: Order) -> None:
        """Переводит новый заказ в статус «оплачен».

        Args:
            order: Заказ в статусе ``new``.
        """
        order.status = OrderStatus.PAID

    def cancel(self, order: Order) -> None:
        """Переводит новый заказ в статус «отменён».

        Args:
            order: Заказ в статусе ``new``.
        """
        order.status = OrderStatus.CANCELLED


class _FinalOrderState(_OrderState):
    """Оплаченный или отменённый заказ: переходов больше нет."""

    def pay(self, order: Order) -> None:
        """Отклоняет оплату конечного заказа.

        Args:
            order: Заказ в статусе ``paid`` или ``cancelled``.

        Raises:
            OrderTransitionNotAllowed: Всегда.
        """
        raise errors.OrderTransitionNotAllowed(id=order.id, status=order.status, action="pay")

    def cancel(self, order: Order) -> None:
        """Отклоняет отмену конечного заказа.

        Args:
            order: Заказ в статусе ``paid`` или ``cancelled``.

        Raises:
            OrderTransitionNotAllowed: Всегда.
        """
        raise errors.OrderTransitionNotAllowed(id=order.id, status=order.status, action="cancel")


_STATES: dict[OrderStatus, _OrderState] = {
    OrderStatus.NEW: _NewOrderState(),
    OrderStatus.PAID: _FinalOrderState(),
    OrderStatus.CANCELLED: _FinalOrderState(),
}


# --- Сущности -------------------------------------------------------------------------


@dataclass(kw_only=True)
class Customer:
    """Клиент магазина.

    Attributes:
        id: Идентификатор; ``None`` до сохранения в хранилище.
        name: Имя клиента.
        email: Email, уникальный среди клиентов.
    """

    id: int | None = None
    name: str
    email: str


@dataclass(kw_only=True)
class Product:
    """Товар со складским остатком.

    Attributes:
        id: Идентификатор; ``None`` до сохранения в хранилище.
        name: Название товара.
        price: Текущая цена за единицу.
        stock: Доступный остаток в единицах.
    """

    id: int | None = None
    name: str
    price: Decimal
    stock: int

    def reserve(self, quantity: int) -> None:
        """Списывает остаток под заказ.

        Args:
            quantity: Сколько единиц зарезервировать.

        Raises:
            InsufficientStock: Остатка меньше, чем запрошено; остаток не меняется.
        """
        if quantity > self.stock:
            raise errors.InsufficientStock(
                product_id=self.id, requested=quantity, available=self.stock
            )
        self.stock -= quantity

    def release(self, quantity: int) -> None:
        """Возвращает остаток, списанный под отменённый заказ.

        Args:
            quantity: Сколько единиц вернуть на склад.
        """
        self.stock += quantity


@dataclass(kw_only=True)
class OrderLine:
    """Строка заказа: один товар в некотором количестве.

    Attributes:
        id: Идентификатор; ``None`` до сохранения в хранилище.
        order_id: Заказ-владелец; проставляется при сохранении заказа.
        product_id: Товар строки.
        quantity: Количество единиц.
        unit_price: Цена за единицу, зафиксированная в момент оформления заказа.
    """

    id: int | None = None
    order_id: int | None = None
    product_id: int
    quantity: int
    unit_price: Decimal

    @property
    def total(self) -> Decimal:
        """Стоимость строки: цена за единицу, умноженная на количество."""
        return self.unit_price * self.quantity


@dataclass(kw_only=True)
class Order:
    """Заказ клиента со строками, скидкой и статусом.

    Attributes:
        id: Идентификатор; ``None`` до сохранения в хранилище.
        customer_id: Клиент, оформивший заказ.
        status: Текущий статус; переходы — через ``pay`` и ``cancel``.
        discount: Сумма скидки, зафиксированная при оформлении.
        created_at: Момент оформления; не участвует в сравнении сущностей — равенство
            определяется данными заказа.
        lines: Строки заказа.
    """

    id: int | None = None
    customer_id: int
    status: OrderStatus = OrderStatus.NEW
    discount: Decimal = Decimal("0")
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC), compare=False)
    lines: list[OrderLine] = field(default_factory=list)

    @property
    def total_quantity(self) -> int:
        """Общее количество единиц товара по всем строкам."""
        return sum(line.quantity for line in self.lines)

    @property
    def subtotal(self) -> Decimal:
        """Сумма заказа до скидки: сумма стоимостей строк."""
        return sum((line.total for line in self.lines), Decimal("0"))

    @property
    def total(self) -> Decimal:
        """Сумма к оплате: ``subtotal`` за вычетом скидки."""
        return self.subtotal - self.discount

    def apply_discount(self, policy: DiscountPolicy) -> None:
        """Рассчитывает скидку выбранной политикой и фиксирует её сумму в заказе.

        Args:
            policy: Политика скидки (Strategy), которой доверен расчёт.
        """
        self.discount = policy.discount_for(self.subtotal, self.total_quantity)

    def pay(self) -> None:
        """Переводит заказ в статус ``paid``.

        Raises:
            OrderTransitionNotAllowed: Заказ уже оплачен или отменён.
        """
        _STATES[self.status].pay(self)

    def cancel(self) -> None:
        """Переводит заказ в статус ``cancelled``.

        Raises:
            OrderTransitionNotAllowed: Заказ уже оплачен или отменён.
        """
        _STATES[self.status].cancel(self)
