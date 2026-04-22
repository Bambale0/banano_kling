"""
Services for the Telegram bot
"""

from .cryptobot_service import CryptoBotService, cryptobot_service
from .kling_service import KlingService, kling_service
from .nano_banana_2_service import NanoBanana2Service, nano_banana_2_service
from .nano_banana_pro_service import NanoBananaProService, nano_banana_pro_service
from .veo_service import VeoService, veo_service

__all__ = [
    "cryptobot_service",
    "CryptoBotService",
    "kling_service",
    "KlingService",
    "nano_banana_pro_service",
    "NanoBananaProService",
    "nano_banana_2_service",
    "NanoBanana2Service",
    "veo_service",
    "VeoService",
]
