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

from . import (
    generation as generation_module,
    lava_checkout as lava_checkout_module,
    payments as payments_module,
)
from .admin import router as admin_router
from .batch_generation import router as batch_generation_router
from .common import router as legacy_common_router
from .freekassa_payments import router as freekassa_payments_router
from .image_analyzer import router as image_analyzer_router
from .notification_campaigns import router as notification_campaigns_router
from .repeat_result_compat import router as repeat_result_compat_router
from .seedance_multimodal_compat import (
    install_seedance_multimodal_runtime_compat,
    router as seedance_multimodal_compat_router,
)
from .support import router as support_router

# Keep payment safety fixes without changing the established user-facing flow.
install_lava_binding_schema_compat()
install_lava_payment_safety(payments_module)
install_lava_invoice_compat(payments_module, lava_checkout_module)
legacy_payments_router = payments_module.router
lava_checkout_router = lava_checkout_module.router

# Seedance needs a narrow media compatibility layer because the established UX
# exposes separate photo and video sub-flows while the provider accepts both in
# one multimodal request. The compatibility router owns media messages only;
# every menu callback, screen and keyboard remains in the legacy generation
# router below it.
install_seedance_multimodal_runtime_compat()
generation_router = Router()
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
common_router = Router()
common_router.include_router(notification_campaigns_router)
common_router.include_router(repeat_result_compat_router)
common_router.include_router(support_router)
common_router.include_router(legacy_common_router)

__all__ = [
    "admin_router",
    "batch_generation_router",
    "common_router",
    "freekassa_payments_router",
    "generation_router",
    "image_analyzer_router",
    "lava_checkout_router",
    "notification_campaigns_router",
    "payments_router",
    "repeat_result_compat_router",
    "seedance_multimodal_compat_router",
    "support_router",
]
