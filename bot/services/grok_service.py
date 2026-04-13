"""Grok Imagine Image-to-Video Service - Kie.ai API"""

import logging
from typing import Dict, List, Optional

from bot.config import config
from bot.services.kling_service import KlingService

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
            "image_urls": image_urls[:7],  # max 7
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


grok_service = GrokService(kie_key=config.KIE_AI_API_KEY)
