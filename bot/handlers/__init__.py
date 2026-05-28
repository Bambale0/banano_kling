"""
Handlers for the Telegram bot
"""

from .admin import router as admin_router
from .batch_generation import router as batch_generation_router
from .common import router as common_router
from .common import start_router
from .feed import router as feed_router
from .generation import router as generation_router
from .image_analyzer import router as image_analyzer_router
from .payments import router as payments_router

__all__ = [
    "common_router",
    "start_router",
    "feed_router",
    "generation_router",
    "payments_router",
    "admin_router",
    "batch_generation_router",
    "image_analyzer_router",
]
