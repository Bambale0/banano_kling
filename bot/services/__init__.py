#!/usr/bin/env python3
# ruff: noqa: I001

"""
Services for the Telegram bot.
"""

import logging
import os

from bot.config import config

logger = logging.getLogger(__name__)

# Legacy APIYI routing stays disabled for Nano Banana 2. This feature branch
# explicitly owns provider selection below: Nexus primary -> Kie fallback.
config.NANOBANANA2_FALLBACK_API_KEY = ""
config.NANOBANANA2_FALLBACK_BASE_URL = ""

from .cryptobot_service import CryptoBotService, cryptobot_service
from .gpt_image_service import GPTImageService, gpt_image_service
from .gemini_omni_service import GeminiOmniService, gemini_omni_service
from .kling_service import KlingService, kling_service
from .kie_market_service import KieMarketService, kie_market_service
from .nano_banana_2_service import NanoBanana2Service, nano_banana_2_service
from .nano_banana_pro_service import NanoBananaProService, nano_banana_pro_service
from .nexus_image_provider import NexusImageProvider
from .seedream_service import SeedreamService, seedream_service
from .veo_service import VeoService, veo_service
from .photo_prompt_vk_compat import install_vk_photo_prompt_instructions


def _configure_nexus_nanobanana_routing() -> None:
    """Use Nexus for Nano Banana 2/Pro while preserving Kie as fallback.

    Nano Banana 2 Lite is intentionally untouched and keeps its dedicated Kie
    Market route inside NanoBanana2Service.
    """

    nexus_api_key = os.getenv("NEXUS_API_KEY", "").strip()
    nexus_base_url = os.getenv("NEXUS_API_BASE_URL", "https://nexusapi.dev").strip().rstrip("/")
    try:
        timeout_seconds = max(30, int(os.getenv("NEXUS_API_TIMEOUT_SECONDS", "180")))
    except ValueError:
        timeout_seconds = 180
    try:
        poll_interval_seconds = max(0.5, float(os.getenv("NEXUS_API_POLL_INTERVAL_SECONDS", "1")))
    except ValueError:
        poll_interval_seconds = 1.0

    # Nano Banana 2 arrives here with Kie as primary because the legacy APIYI
    # environment route is disabled above. Keep that exact instance as fallback.
    banana2_kie = nano_banana_2_service.fallback_provider or nano_banana_2_service.primary_provider

    # Nano Banana Pro may still have legacy APIYI credentials in production env.
    # Its configured fallback is Kie; if no legacy provider exists, primary is Kie.
    banana_pro_kie = nano_banana_pro_service.fallback_provider or nano_banana_pro_service.primary_provider

    if not nexus_api_key:
        nano_banana_2_service.primary_provider = banana2_kie
        nano_banana_2_service.fallback_provider = None
        nano_banana_pro_service.primary_provider = banana_pro_kie
        nano_banana_pro_service.fallback_provider = None
        logger.warning(
            "NEXUS_API_KEY is not configured; Nano Banana 2/Pro remain on Kie.ai"
        )
        return

    nano_banana_2_service.primary_provider = NexusImageProvider(
        api_key=nexus_api_key,
        model_name="nano-banana-2",
        base_url=nexus_base_url,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        max_references=4,
    )
    nano_banana_2_service.fallback_provider = banana2_kie

    nano_banana_pro_service.primary_provider = NexusImageProvider(
        api_key=nexus_api_key,
        model_name="nano-banana-pro",
        base_url=nexus_base_url,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        max_references=4,
    )
    nano_banana_pro_service.fallback_provider = banana_pro_kie

    logger.info(
        "Nano Banana routing: Nexus primary (2 + Pro), Kie.ai fallback; Lite unchanged"
    )


_configure_nexus_nanobanana_routing()

# Keep Telegram photo analysis aligned with the prompt that produces the best
# results in the VK bot. The patch preserves Telegram's structured JSON output,
# voice mode and provider fallback chain.
install_vk_photo_prompt_instructions()

__all__ = [
    "CryptoBotService",
    "GPTImageService",
    "GeminiOmniService",
    "KieMarketService",
    "KlingService",
    "NanoBanana2Service",
    "NanoBananaProService",
    "NexusImageProvider",
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
