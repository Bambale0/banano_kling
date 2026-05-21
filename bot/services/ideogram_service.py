"""Ideogram Character service via Kie.ai."""

from __future__ import annotations

from typing import Dict, List, Optional

from bot.config import config
from bot.services.kling_service import KlingService


_IMAGE_SIZE_BY_RATIO = {
    "1:1": "square",
    "16:9": "landscape_16_9",
    "9:16": "portrait_16_9",
    "4:3": "landscape_4_3",
    "3:4": "portrait_4_3",
}


class IdeogramService(KlingService):
    async def generate_character(
        self,
        prompt: str,
        reference_image_urls: List[str],
        aspect_ratio: str = "1:1",
        rendering_speed: str = "BALANCED",
        style: str = "AUTO",
        expand_prompt: bool = True,
        num_images: str = "1",
        nsfw_checker: bool = False,
        callback_url: Optional[str] = None,
    ) -> Optional[Dict]:
        payload = {
            "model": "ideogram/character",
            "input": {
                "prompt": prompt,
                "reference_image_urls": reference_image_urls[:4],
                "rendering_speed": rendering_speed,
                "style": style,
                "expand_prompt": expand_prompt,
                "image_size": _IMAGE_SIZE_BY_RATIO.get(aspect_ratio, "square"),
                "num_images": str(num_images),
                "nsfw_checker": nsfw_checker,
            },
        }
        if callback_url:
            payload["callBackUrl"] = callback_url
        return await self._kie_post("/api/v1/jobs/createTask", payload)


ideogram_service = IdeogramService(kie_key=config.KIE_AI_API_KEY)
