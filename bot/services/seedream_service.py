import logging
from typing import Dict, List, Optional

from bot.config import config
from bot.services.kling_service import KlingService
from bot.services.media_input_utils import \
    image_sources_to_provider_safe_png_urls

logger = logging.getLogger(__name__)


class SeedreamService(KlingService):
    """Seedream 4.5 Edit via Kie.ai Market API."""

    SUPPORTED_MODELS = {"seedream/4.5-edit"}
    SUPPORTED_ASPECT_RATIOS = {
        "1:1",
        "4:3",
        "3:4",
        "16:9",
        "9:16",
        "2:3",
        "3:2",
        "21:9",
    }
    SUPPORTED_QUALITIES = {"basic", "high"}

    async def generate_image(
        self,
        prompt: str,
        image_urls: List[str],
        *,
        aspect_ratio: str = "1:1",
        quality: str = "basic",
        nsfw_checker: bool = False,
        callBackUrl: Optional[str] = None,
        model: str = "seedream/4.5-edit",
    ) -> Optional[Dict]:
        """Create Seedream 4.5 Edit task."""
        if model not in self.SUPPORTED_MODELS:
            logger.error("Unsupported Seedream model: %s", model)
            return None
        if not prompt or not prompt.strip():
            logger.error("Seedream prompt is required")
            return None
        if len(prompt) > 3000:
            prompt = prompt[:3000]
        if not image_urls:
            logger.error("Seedream requires at least one image_url")
            return None
        if aspect_ratio not in self.SUPPORTED_ASPECT_RATIOS:
            logger.warning(
                "Unsupported Seedream aspect ratio %s, fallback to 1:1", aspect_ratio
            )
            aspect_ratio = "1:1"
        if quality not in self.SUPPORTED_QUALITIES:
            logger.warning(
                "Unsupported Seedream quality %s, fallback to basic", quality
            )
            quality = "basic"

        payload = {
            "model": model,
            "input": {
                "prompt": prompt,
                "image_urls": image_urls[:14],
                "aspect_ratio": aspect_ratio,
                "quality": quality,
                "nsfw_checker": nsfw_checker,
            },
        }
        if callBackUrl:
            payload["callBackUrl"] = callBackUrl
        response = await self._kie_post("/api/v1/jobs/createTask", payload)

        if (
            isinstance(response, dict)
            and response.get("error") == "api_error"
            and "file type not supported" in (response.get("message") or "").lower()
        ):
            normalized_image_urls = image_sources_to_provider_safe_png_urls(
                image_urls[:14]
            )
            if normalized_image_urls != image_urls[:14]:
                logger.warning(
                    "Seedream retry with normalized PNG references after file type error"
                )
                retry_payload = {
                    "model": model,
                    "input": {
                        "prompt": prompt,
                        "image_urls": normalized_image_urls,
                        "aspect_ratio": aspect_ratio,
                        "quality": quality,
                        "nsfw_checker": nsfw_checker,
                    },
                }
                if callBackUrl:
                    retry_payload["callBackUrl"] = callBackUrl
                response = await self._kie_post(
                    "/api/v1/jobs/createTask", retry_payload
                )

        return response


seedream_service = SeedreamService(kie_key=config.KIE_AI_API_KEY)
