"""
Handlers for the Telegram bot
"""

import importlib
import logging

from .admin import router as admin_router
from .batch_generation import router as batch_generation_router
from .common import router as common_router
from .common import start_router
from .feed import router as feed_router
from .generation import router as generation_router
from .image_analyzer import router as image_analyzer_router
from .payments import router as payments_router

logger = logging.getLogger(__name__)


def _load_optional_router(module_name: str):
    try:
        module = importlib.import_module(f"bot.handlers.{module_name}")
    except ModuleNotFoundError as exc:
        if exc.name == f"bot.handlers.{module_name}":
            return None
        raise
    router = getattr(module, "router", None)
    if router is None:
        logger.warning("Optional handler %s has no router", module_name)
    return router


optional_admin_routers = [
    router
    for router in (
        _load_optional_router("admin_packages"),
        _load_optional_router("admin_referral_tools"),
        _load_optional_router("admin_push_scenarios"),
    )
    if router is not None
]

__all__ = [
    "common_router",
    "start_router",
    "feed_router",
    "generation_router",
    "payments_router",
    "admin_router",
    "optional_admin_routers",
    "batch_generation_router",
    "image_analyzer_router",
]
