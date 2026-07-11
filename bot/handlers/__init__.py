"""
Handlers for the Telegram bot.
"""

from aiogram import Router

from .admin import router as admin_router
from .batch_generation import router as batch_generation_router
from .common import router as legacy_common_router
from .generation import router as generation_router
from .image_analyzer import router as image_analyzer_router
from .payments import router as payments_router
from .support import router as support_router

# main.py already places common_router last. Keep that contract while ensuring
# support FSM handlers run before broad legacy common handlers.
common_router = Router()
common_router.include_router(support_router)
common_router.include_router(legacy_common_router)

__all__ = [
    "common_router",
    "generation_router",
    "payments_router",
    "admin_router",
    "batch_generation_router",
    "image_analyzer_router",
    "support_router",
]
