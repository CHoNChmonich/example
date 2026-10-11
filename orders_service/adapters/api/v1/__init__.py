"""API v1: контроллер и фабрика маршрутизатора."""

from .controller import Controller
from .router import HEALTHCHECK_PATH, create_router

__all__ = ["HEALTHCHECK_PATH", "Controller", "create_router"]
