"""
Handlers for the Telegram bot.
"""

from aiogram import Router

from .admin import router as admin_router
from .batch_generation import router as batch_generation_router
from .common import router as legacy_common_router
from .generation import router as generation_router
from .image_analyzer import router as legacy_image_analyzer_router
from .notification_campaigns import router as notification_campaigns_router
from .payments import router as payments_router
from .prompt_analyzer_v2 import router as prompt_analyzer_v2_router
from .repeat_result_compat import router as repeat_result_compat_router
from .support import router as support_router

# The unified analyzer must run before the legacy photo/video analyzer. It owns
# only the photo-to-prompt callback and waiting_for_photo state; the legacy router
# continues to handle video-to-prompt and compatibility scenarios.
image_analyzer_router = Router()
image_analyzer_router.include_router(prompt_analyzer_v2_router)
image_analyzer_router.include_router(legacy_image_analyzer_router)

# main.py already places common_router last. Keep that contract while ensuring
# specific support/repeat handlers run before broad legacy common handlers.
common_router = Router()
common_router.include_router(notification_campaigns_router)
common_router.include_router(repeat_result_compat_router)
common_router.include_router(support_router)
common_router.include_router(legacy_common_router)

__all__ = [
    "admin_router",
    "batch_generation_router",
    "common_router",
    "generation_router",
    "image_analyzer_router",
    "notification_campaigns_router",
    "payments_router",
    "prompt_analyzer_v2_router",
    "repeat_result_compat_router",
    "support_router",
]
