"""
Services for the Telegram bot
"""

from .kling_service import KlingService, kling_service
from .nano_banana_2_service import NanoBanana2Service, nano_banana_2_service
from .nano_banana_pro_service import NanoBananaProService, nano_banana_pro_service
from .robokassa_service import robokassa_service
from .yookassa_service import yookassa_service

__all__ = [
    "kling_service",
    "KlingService",
    "nano_banana_pro_service",
    "NanoBananaProService",
    "nano_banana_2_service",
    "NanoBanana2Service",
    "yookassa_service",
    "robokassa_service",
]
