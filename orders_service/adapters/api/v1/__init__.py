"""API v1: контроллер и фабрика маршрутизатора."""

from .controller import Controller
from .router import create_router

__all__ = ["Controller", "create_router"]
