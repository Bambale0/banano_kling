"""
Services for the Telegram bot
"""

from .cryptobot_service import CryptoBotService, cryptobot_service
from .gpt_image_service import GPTImageService, gpt_image_service
from .gemini_omni_service import GeminiOmniService, gemini_omni_service
from .kling_service import KlingService, kling_service
from .kie_market_service import KieMarketService, kie_market_service
from .nano_banana_2_service import NanoBanana2Service, nano_banana_2_service
from .nano_banana_pro_service import NanoBananaProService, nano_banana_pro_service
from .seedream_service import SeedreamService, seedream_service
from .veo_service import VeoService, veo_service
from .photo_prompt_vk_compat import install_vk_photo_prompt_instructions

# Keep Telegram photo analysis aligned with the prompt that produces the best
# results in the VK bot. The patch preserves Telegram's structured JSON output,
# voice mode and provider fallback chain.
install_vk_photo_prompt_instructions()

__all__ = [
    "cryptobot_service",
    "CryptoBotService",
    "gpt_image_service",
    "GPTImageService",
    "gemini_omni_service",
    "GeminiOmniService",
    "kling_service",
    "KlingService",
    "kie_market_service",
    "KieMarketService",
    "nano_banana_pro_service",
    "NanoBananaProService",
    "nano_banana_2_service",
    "NanoBanana2Service",
    "seedream_service",
    "SeedreamService",
    "veo_service",
    "VeoService",
]
