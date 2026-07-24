#!/usr/bin/env python3
# ruff: noqa: I001

"""
Services for the Telegram bot.
"""

from bot.config import config

# Product routing decision: regular Nano Banana 2 and Nano Banana Pro must use
# Kie.ai even when legacy APIYI credentials are still present in the deployment
# environment. Their service modules inspect these attributes during import, so
# clear them before importing the model singletons below. Nano Banana 2 Lite is
# a separate Kie Market route and is not affected.
config.NANOBANANA2_FALLBACK_API_KEY = ""
config.NANOBANANA2_FALLBACK_BASE_URL = ""
config.NANO_BANANA_PRO_FALLBACK_API_KEY = ""
config.NANO_BANANA_PRO_FALLBACK_BASE_URL = ""

from .cryptobot_service import CryptoBotService, cryptobot_service
from .gpt_image_service import GPTImageService, gpt_image_service
from .gemini_omni_service import GeminiOmniService, gemini_omni_service
from .kling_service import KlingService, kling_service
from .kie_market_service import KieMarketService, kie_market_service
from .nano_banana_2_service import NanoBanana2Service, nano_banana_2_service
from .nano_banana_pro_service import NanoBananaProService, nano_banana_pro_service
from .seedream_service import SeedreamService, seedream_service
from .veo_service import VeoService, veo_service

__all__ = [
    "CryptoBotService",
    "GPTImageService",
    "GeminiOmniService",
    "KieMarketService",
    "KlingService",
    "NanoBanana2Service",
    "NanoBananaProService",
    "SeedreamService",
    "VeoService",
    "cryptobot_service",
    "gemini_omni_service",
    "gpt_image_service",
    "kie_market_service",
    "kling_service",
    "nano_banana_2_service",
    "nano_banana_pro_service",
    "seedream_service",
    "veo_service",
]
