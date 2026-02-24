"""
Handlers for the Telegram bot
"""

from .admin import router as admin_router
from .batch_generation import router as batch_generation_router
from .common import router as common_router
from .generation import router as generation_router
from .payments import router as payments_router
from .start import router as start_router
from .settings import router as settings_router
from .image_generation import router as image_generation_router
from .image_editing import router as image_editing_router
from .video_generation import router as video_generation_router

__all__ = [
    "common_router",
    "generation_router",
    "payments_router",
    "admin_router",
    "batch_generation_router",
    "start_router",
    "settings_router",
    "image_generation_router",
    "image_editing_router",
    "video_generation_router",
]
