#!/usr/bin/env python3
# ruff: noqa: I001

"""
Services for the Telegram bot.
"""

import logging
import os

from bot.config import config

logger = logging.getLogger(__name__)

# Legacy APIYI routing stays disabled for Nano Banana 2. Provider selection is
# owned centrally below so Telegram/Mini App handlers keep their existing
# contracts and do not need provider-specific branches.
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
from .rendergrid_nano_banana_provider import RenderGridNanoBananaProvider
from .seedream_service import SeedreamService, seedream_service
from .veo_service import VeoService, veo_service
from .photo_prompt_vk_compat import install_vk_photo_prompt_instructions


def _env_flag(name: str, default: bool = False) -> bool:
    fallback = "1" if default else "0"
    return os.getenv(name, fallback).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _configure_nanobanana_routing() -> None:
    """Configure internal Nano Banana providers without changing product UX.

    With ``NANOBANANA_RENDERGRID_ENABLED=1`` RenderGrid becomes the primary
    provider for Nano Banana 2 and Nano Banana Pro. Their existing queued KIE
    clients become the sole technical fallback. Individual model flags can
    override the global switch for canary rollout. Nano Banana 2 Lite remains
    on its dedicated KIE Market route inside NanoBanana2Service.

    With the RenderGrid switch disabled the previous KIE -> Nexus routing is
    preserved exactly, which makes rollback an environment-only operation.
    """

    nexus_api_key = os.getenv("NEXUS_API_KEY", "").strip()
    nexus_base_url = os.getenv("NEXUS_API_BASE_URL", "https://nexusapi.dev").strip().rstrip("/")
    try:
        nexus_timeout_seconds = max(
            30,
            int(os.getenv("NEXUS_API_TIMEOUT_SECONDS", "180")),
        )
    except ValueError:
        nexus_timeout_seconds = 180
    try:
        nexus_poll_interval_seconds = max(
            0.5,
            float(os.getenv("NEXUS_API_POLL_INTERVAL_SECONDS", "1")),
        )
    except ValueError:
        nexus_poll_interval_seconds = 1.0

    # Module-level service instances are created with the KIE client available.
    # Keep resolving defensively in case a legacy branch wired Nexus first.
    banana2_kie = nano_banana_2_service.primary_provider
    if isinstance(banana2_kie, NexusImageProvider):
        banana2_kie = nano_banana_2_service.fallback_provider

    banana_pro_kie = nano_banana_pro_service.primary_provider
    if isinstance(banana_pro_kie, NexusImageProvider):
        banana_pro_kie = nano_banana_pro_service.fallback_provider

    if banana2_kie is None or banana_pro_kie is None:
        raise RuntimeError("Kie.ai Nano Banana provider wiring is unavailable")

    global_rendergrid_enabled = _env_flag("NANOBANANA_RENDERGRID_ENABLED", False)
    banana2_rendergrid_enabled = _env_flag(
        "NANOBANANA2_RENDERGRID_ENABLED",
        global_rendergrid_enabled,
    )
    banana_pro_rendergrid_enabled = _env_flag(
        "NANOBANANAPRO_RENDERGRID_ENABLED",
        global_rendergrid_enabled,
    )
    rendergrid_api_key = os.getenv("RENDERGRID_API_KEY", "").strip()
    rendergrid_base_url = os.getenv(
        "RENDERGRID_BASE_URL",
        "https://api.rendergrid.io/api/public/v1",
    ).strip().rstrip("/")
    reference_guidance_enabled = _env_flag(
        "RENDERGRID_REFERENCE_GUIDANCE_ENABLED",
        True,
    )

    def configure_rendergrid_or_kie(
        *,
        enabled: bool,
        service,
        kie_provider,
        model_env: str,
        default_model: str,
        label: str,
    ) -> bool:
        if not enabled:
            return False

        # An enabled feature with a missing key must fail safe to KIE, not to a
        # third provider. This keeps the requested RenderGrid -> KIE contract.
        if not rendergrid_api_key:
            service.primary_provider = kie_provider
            service.fallback_provider = None
            logger.warning(
                "%s: RenderGrid enabled but RENDERGRID_API_KEY is missing; using KIE only",
                label,
            )
            return True

        provider_model = os.getenv(model_env, default_model).strip() or default_model
        service.primary_provider = RenderGridNanoBananaProvider(
            api_key=rendergrid_api_key,
            model_name=provider_model,
            base_url=rendergrid_base_url,
            max_references=8,
            reference_guidance_enabled=reference_guidance_enabled,
        )
        service.fallback_provider = kie_provider
        logger.info(
            "%s routing: RenderGrid primary model=%s, KIE technical fallback",
            label,
            provider_model,
        )
        return True

    banana2_managed = configure_rendergrid_or_kie(
        enabled=banana2_rendergrid_enabled,
        service=nano_banana_2_service,
        kie_provider=banana2_kie,
        model_env="RENDERGRID_NANO_BANANA_2_MODEL",
        default_model="nano-banana-2",
        label="Nano Banana 2",
    )
    banana_pro_managed = configure_rendergrid_or_kie(
        enabled=banana_pro_rendergrid_enabled,
        service=nano_banana_pro_service,
        kie_provider=banana_pro_kie,
        model_env="RENDERGRID_NANO_BANANA_PRO_MODEL",
        default_model="nano-banana-pro",
        label="Nano Banana Pro",
    )

    # Models not managed by RenderGrid keep the previous KIE -> Nexus route.
    if not banana2_managed:
        nano_banana_2_service.primary_provider = banana2_kie
        nano_banana_2_service.fallback_provider = (
            NexusImageProvider(
                api_key=nexus_api_key,
                model_name="nano-banana-2",
                base_url=nexus_base_url,
                timeout_seconds=nexus_timeout_seconds,
                poll_interval_seconds=nexus_poll_interval_seconds,
                max_references=8,
            )
            if nexus_api_key
            else None
        )

    if not banana_pro_managed:
        nano_banana_pro_service.primary_provider = banana_pro_kie
        nano_banana_pro_service.fallback_provider = (
            NexusImageProvider(
                api_key=nexus_api_key,
                model_name="nano-banana-pro",
                base_url=nexus_base_url,
                timeout_seconds=nexus_timeout_seconds,
                poll_interval_seconds=nexus_poll_interval_seconds,
                max_references=8,
            )
            if nexus_api_key
            else None
        )

    if not banana2_managed or not banana_pro_managed:
        logger.info(
            "Nano Banana legacy routing retained for non-RenderGrid models: KIE primary, "
            "Nexus fallback=%s",
            bool(nexus_api_key),
        )


_configure_nanobanana_routing()

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
    "RenderGridNanoBananaProvider",
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
