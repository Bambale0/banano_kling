"""
Handlers for the Telegram bot
"""

from .admin import router as admin_router
from .batch_generation import router as batch_generation_router
from .common import router as common_router
from .generation import router as generation_router
from .payments import router as payments_router

__all__ = [
    "common_router",
    "generation_router",
    "payments_router",
    "admin_router",
    "batch_generation_router",
]
