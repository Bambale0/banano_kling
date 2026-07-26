"""
Handlers for the Telegram bot.
"""

from aiogram import Router

from .admin import router as admin_router
from .batch_generation import router as batch_generation_router
from .common import router as common_router
from .generation import router as legacy_generation_router
from .image_analyzer import router as image_analyzer_router
from .payments import router as payments_router
from .video_generation_compat import router as video_generation_compat_router

# Advanced video callbacks must run before the broad legacy router.
generation_router = Router()
generation_router.include_router(video_generation_compat_router)
generation_router.include_router(legacy_generation_router)

__all__ = [
    "common_router",
    "generation_router",
    "payments_router",
    "admin_router",
    "batch_generation_router",
    "image_analyzer_router",
    "video_generation_compat_router",
]
