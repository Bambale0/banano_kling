"""Grok Imagine Image-to-Video Service - Kie.ai API"""

import logging
from typing import Dict, List, Optional

from bot.config import config
from bot.services.kling_service import KlingService
from bot.services.media_input_utils import image_sources_to_provider_safe_png_urls

logger = logging.getLogger(__name__)


class GrokService(KlingService):
    """Wrapper for Grok Imagine via Kie.ai"""

    async def generate_image_to_video(
        self,
        image_urls: List[str],
        prompt: str = "",
        mode: str = "normal",
        duration: int = 6,
        resolution: str = "720p",
        aspect_ratio: str = "16:9",
        nsfw_checker: bool = False,
        callBackUrl: Optional[str] = None,
    ) -> Optional[Dict]:
        """Generate video from images using Grok Imagine"""
        input_data = {
            "image_urls": image_sources_to_provider_safe_png_urls(
                image_urls[:7]
            ),  # max 7
            "prompt": prompt,
            "mode": mode,
            "duration": duration,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "nsfw_checker": nsfw_checker,
        }
        payload = {
            "model": "grok-imagine/image-to-video",
            "input": input_data,
        }
        if callBackUrl:
            payload["callBackUrl"] = callBackUrl
        return await self._kie_post("/api/v1/jobs/createTask", payload)

    async def generate_image_to_image(
        self,
        image_urls: List[str],
        prompt: str = "",
        nsfw_checker: bool = False,
        callBackUrl: Optional[str] = None,
    ) -> Optional[Dict]:
        """Generate image from image + prompt using Grok Imagine i2i."""
        if len(image_urls) == 0:
            logger.error("No image_urls provided for Grok i2i")
            return None

        safe_image_urls = image_sources_to_provider_safe_png_urls(image_urls)

        image_refs = " ".join(f"@image{i + 1}" for i in range(len(safe_image_urls)))
        clean_prompt = str(prompt or "").strip()
        if image_refs and not clean_prompt.startswith("@image"):
            clean_prompt = f"{image_refs} {clean_prompt}".strip()

        input_data = {
            "prompt": clean_prompt,
            "image_urls": safe_image_urls,
            # Kie checker must stay disabled for Grok i2i.
            # The model/provider will handle generation rules itself.
            "nsfw_checker": False,
        }
        payload = {
            "model": "grok-imagine/image-to-image",
            "input": input_data,
        }
        if callBackUrl:
            payload["callBackUrl"] = callBackUrl

        logger.info(
            "Grok i2i payload prepared: refs=%s nsfw_checker=false prompt_prefix=%s",
            len(safe_image_urls),
            clean_prompt[:80],
        )
        return await self._kie_post("/api/v1/jobs/createTask", payload)


grok_service = GrokService(kie_key=config.KIE_AI_API_KEY)
