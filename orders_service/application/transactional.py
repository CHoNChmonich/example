"""Метод-обёртка ``@transactional``: граница транзакции = публичный метод сервиса.

При вызове обёртка создаёт Unit of Work через ``self.uow_factory`` (внутри — сессия и
репозитории), передаёт его методу первым аргументом после ``self`` и делает ``commit`` при
нормальном выходе. При исключении commit не выполняется, откат делает ``__aexit__`` UoW,
исключение уходит наружу. Снаружи метод вызывается без ``uow``.

Это Python-декоратор (аспект), а не GoF Decorator: он меняет сигнатуру метода и применяется
статически. Аналог ``DecoratedFunction`` + ``TransactionContext`` из hex_arch, но без
глобального реестра и thread-local сессии: фабрика приходит в сервис через конструктор.

Правила: вложенных транзакций нет — транзакционный метод не вызывает другой транзакционный
метод; общая логика выносится в приватные хелперы, принимающие ``uow``. Чтения тоже идут через
обёртку: репозитории существуют только внутри UoW.
"""

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Concatenate, Protocol

from orders_service.application import interfaces


class TransactionalService(Protocol):
    """Что обёртка требует от сервиса.

    Attributes:
        uow_factory: Фабрика Unit of Work, из которой обёртка берёт транзакцию на каждый вызов.
    """

    uow_factory: interfaces.UnitOfWorkFactory


def transactional[S: TransactionalService, **P, R](
    method: Callable[Concatenate[S, interfaces.UnitOfWork, P], Awaitable[R]],
) -> Callable[Concatenate[S, P], Awaitable[R]]:
    """Выполняет метод сервиса в транзакции нового Unit of Work.

    ``self`` обёртки объявлен позиционно-только: иначе тип ``functools.wraps`` не сходится
    с ``Concatenate`` под ``mypy --strict``.

    Args:
        method: Асинхронный метод сервиса, принимающий ``uow`` первым параметром после ``self``.

    Returns:
        Метод с той же сигнатурой без параметра ``uow``: он создаёт UoW сам, коммитит при
        нормальном выходе и пропускает исключения метода наружу без commit.

    Raises:
        StorageUnavailable: Поднимает UoW при сбое хранилища на commit или откате.
    """

    @wraps(method)
    async def wrapper(self: S, /, *args: P.args, **kwargs: P.kwargs) -> R:
        """Создаёт UoW, вызывает исходный метод и фиксирует транзакцию при успехе.

        Args:
            self: Сервис с фабрикой ``uow_factory``; позиционно-только ради типизации.
            *args: Позиционные аргументы исходного метода, идущие после ``uow``.
            **kwargs: Именованные аргументы исходного метода.

        Returns:
            Результат исходного метода.
        """
        async with self.uow_factory.create() as uow:
            result = await method(self, uow, *args, **kwargs)
            await uow.commit()
            return result

    return wrapper
