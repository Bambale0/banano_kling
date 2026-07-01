"""Grok Imagine Service - Image-to-Video, Text-to-Image, Image-to-Image via Kie.ai API"""

import logging
from typing import Dict, List, Optional

from bot.config import config
from bot.services.kling_service import KlingService, normalize_kie_image_url

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
        """Generate video from images using Grok Imagine.

        Kie.ai Grok Imagine требует прямые публичные URL (не filePath от file-url-upload).
        """
        # Normalize relative URLs to absolute
        urls = [normalize_kie_image_url(u) for u in image_urls[:7]]
        logger.info(
            "Grok Imagine image-to-video: urls=%s, prompt=%.200s..., mode=%s, duration=%s, resolution=%s",
            urls,
            prompt,
            mode,
            duration,
            resolution,
        )

        input_data = {
            "image_urls": urls,
            "prompt": prompt,
            "mode": mode,
            "duration": str(duration),
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
        result = await self._kie_post("/api/v1/jobs/createTask", payload)
        if result and result.get("error"):
            logger.error(
                "Grok Imagine createTask failed: %s. urls=%s",
                result,
                urls,
            )
        return result

    async def generate_text_to_image(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
        enable_pro: bool = False,
        nsfw_checker: bool = False,
        callback_url: Optional[str] = None,
    ) -> Optional[Dict]:
        """Generate image from text using Grok Imagine. Returns {'task_id': ...}"""
        payload = {
            "model": "grok-imagine/text-to-image",
            "input": {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "enable_pro": enable_pro,
                "nsfw_checker": nsfw_checker,
            },
        }
        if callback_url:
            payload["callBackUrl"] = callback_url
        resp = await self._kie_post("/api/v1/jobs/createTask", payload)
        if resp and "task_id" in resp:
            return resp
        return None

    async def generate_image_to_image(
        self,
        image_url: str,
        prompt: str = "",
        nsfw_checker: bool = False,
        callback_url: Optional[str] = None,
    ) -> Optional[Dict]:
        """Transform image using Grok Imagine. Returns {'task_id': ...}

        Kie.ai Grok Imagine требует прямые публичные URL (не filePath от file-url-upload).
        """
        normalized_url = normalize_kie_image_url(image_url)

        payload = {
            "model": "grok-imagine/image-to-image",
            "input": {
                "image_urls": [normalized_url],
                "prompt": prompt,
                "nsfw_checker": nsfw_checker,
            },
        }
        if callback_url:
            payload["callBackUrl"] = callback_url
        resp = await self._kie_post("/api/v1/jobs/createTask", payload)
        if resp and "task_id" in resp:
            return resp
        return None


grok_service = GrokService(kie_key=config.KIE_AI_API_KEY)