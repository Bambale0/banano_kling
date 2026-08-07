#!/usr/bin/env python3
"""
Handlers for the Telegram bot.
"""

from aiogram import Router

from bot.services.lava_binding_schema_compat import (
    install_lava_binding_schema_compat,
)
from bot.services.lava_invoice_compat import install_lava_invoice_compat
from bot.services.lava_payment_safety import install_lava_payment_safety
from bot.services.publication_scope_postgres_compat import (
    install_publication_scope_postgres_compat,
)

from . import trends_compat as trends_compat_module
from .feed_model_filter_compat import install_feed_model_filter_compat
from .feed_model_filter_compat import router as feed_model_filter_compat_router
from .miniapp_regression_safety import install_miniapp_regression_safety
from .own_profile_feed_compat import install_own_profile_feed_compat
from .profile_feed_deeplink_compat import install_profile_feed_deeplink_compat

# Publication scope must be installed before generation/common/miniapp import
# their database and keyboard functions. This keeps the established flow while
# adding a separate "profile only" state next to the public discovery feed.
from .publication_scope_compat import (
    install_common_publication_scope_compat,
    install_publication_scope_compat,
)
from .publication_scope_compat import router as publication_scope_compat_router
from .trend_text_upload import install_text_trend_upload
from .trend_text_upload import router as trend_text_upload_router
from .trend_video_compat import install_trend_video_compat
from .trend_video_compat import router as trend_video_compat_router
from .trends_compat import install_trends_compat
from .trends_compat import router as trends_compat_router

install_publication_scope_postgres_compat()
install_publication_scope_compat()

from . import admin as admin_module
from . import common as common_module
from . import (
    generation as generation_module,
)
from . import (
    lava_checkout as lava_checkout_module,
)
from . import (
    payments as payments_module,
)
from .batch_generation import router as batch_generation_router
from .freekassa_payments import router as freekassa_payments_router
from .image_analyzer import router as legacy_image_analyzer_router
from .notification_campaigns import router as notification_campaigns_router
from .photo_prompt_vk_result_compat import install_vk_photo_prompt_result_compat
from .prompt_analyzer_v2 import router as prompt_analyzer_v2_router
from .repeat_result_compat import router as repeat_result_compat_router
from .seedance_25_fullstack import install_seedance_25_fullstack
from .seedance_25_fullstack import router as seedance_25_fullstack_router
from .seedance_25_preview import install_seedance_25_preview
from .seedance_25_preview import router as seedance_25_preview_router
from .seedance_multimodal_compat import (
    install_seedance_multimodal_runtime_compat,
)
from .seedance_multimodal_compat import (
    router as seedance_multimodal_compat_router,
)
from .support import router as support_router

admin_router = admin_module.router

# Keep payment safety fixes without changing the established user-facing flow.
install_lava_binding_schema_compat()
install_lava_payment_safety(payments_module)
install_lava_invoice_compat(payments_module, lava_checkout_module)
legacy_payments_router = payments_module.router
lava_checkout_router = lava_checkout_module.router
legacy_common_router = common_module.router

# Ordinary photo-only prompt analysis should use the same compact result structure
# as the VK bot. Voice-only and photo+voice keep the richer Telegram result.
install_vk_photo_prompt_result_compat()

# The unified analyzer owns text, photo, and voice prompt creation. Keep it
# before the legacy analyzer, which still handles video-to-prompt and fallback
# compatibility routes using the same FSM state.
image_analyzer_router = Router()
image_analyzer_router.include_router(prompt_analyzer_v2_router)
image_analyzer_router.include_router(legacy_image_analyzer_router)

# Seedance 2.0 keeps its established multimodal compatibility layer. Seedance
# 2.5 is installed as a separate admin-only full-stack preview. The full-stack
# router runs before the preview router so it can perform ffprobe validation for
# Telegram document/video/audio inputs while preserving the established image UX.
install_seedance_multimodal_runtime_compat()
install_seedance_25_fullstack()
install_seedance_25_preview()
generation_router = Router()
generation_router.include_router(publication_scope_compat_router)
generation_router.include_router(seedance_25_fullstack_router)
generation_router.include_router(seedance_25_preview_router)
generation_router.include_router(seedance_multimodal_compat_router)
generation_router.include_router(generation_module.router)

# Provider-specific payment handlers run before the broad legacy payments router,
# while generation and photo analysis keep the original UX routing.
payments_router = Router()
payments_router.include_router(lava_checkout_router)
payments_router.include_router(freekassa_payments_router)
payments_router.include_router(legacy_payments_router)

# Keep the established common-menu flow. Specific background/support handlers are
# included before the broad legacy common router without replacing its UI.
install_common_publication_scope_compat(common_module)
install_profile_feed_deeplink_compat(common_module)
install_trends_compat(common_module, generation_module, admin_module)
install_text_trend_upload(trends_compat_module)
install_trend_video_compat(trends_compat_module)
install_feed_model_filter_compat(common_module)
install_own_profile_feed_compat()
install_miniapp_regression_safety()
common_router = Router()
common_router.include_router(trend_video_compat_router)
common_router.include_router(trend_text_upload_router)
common_router.include_router(trends_compat_router)
common_router.include_router(feed_model_filter_compat_router)
common_router.include_router(notification_campaigns_router)
common_router.include_router(repeat_result_compat_router)
common_router.include_router(support_router)
common_router.include_router(legacy_common_router)

__all__ = [
    "admin_router",
    "batch_generation_router",
    "common_router",
    "feed_model_filter_compat_router",
    "freekassa_payments_router",
    "generation_router",
    "image_analyzer_router",
    "lava_checkout_router",
    "notification_campaigns_router",
    "payments_router",
    "prompt_analyzer_v2_router",
    "publication_scope_compat_router",
    "repeat_result_compat_router",
    "seedance_25_fullstack_router",
    "seedance_25_preview_router",
    "seedance_multimodal_compat_router",
    "support_router",
    "trend_text_upload_router",
    "trend_video_compat_router",
    "trends_compat_router",
]
