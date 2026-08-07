"""Kie.ai adapter for Bytedance Seedance 2.5.

Seedance 2.5 uses the same unified Kie jobs API as the existing Seedance 2.0
adapter, but it is kept separate so model-specific limits can evolve without
changing the stable 2.0 production path.
"""

from __future__ import annotations

import logging
from typing import Any

from bot.config import config
from bot.services.kling_service import KlingService

logger = logging.getLogger(__name__)


class Seedance25Service(KlingService):
    MODEL_NAME = "bytedance/seedance-2-5"
    ALLOWED_RATIOS = {"16:9", "9:16", "1:1"}
    ALLOWED_RESOLUTIONS = {"720p"}
    ALLOWED_DURATIONS = {5, 10, 15}
    MAX_REFERENCE_IMAGES = 9
    MAX_REFERENCE_VIDEOS = 3
    MAX_REFERENCE_AUDIO = 3
    MAX_PROMPT_LENGTH = 20_000

    async def generate_video(
        self,
        prompt: str,
        *,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        resolution: str = "720p",
        reference_image_urls: list[str] | None = None,
        reference_video_urls: list[str] | None = None,
        reference_audio_urls: list[str] | None = None,
        return_last_frame: bool = False,
        generate_audio: bool = True,
        callBackUrl: str | None = None,
    ) -> dict[str, Any]:
        """Create a Seedance 2.5 task through Kie's unified jobs endpoint.

        The adapter intentionally exposes only parameters confirmed by the
        current Kie Seedance 2.5 request example. First/last-frame mode is not
        mixed with multimodal references here, avoiding the mutually-exclusive
        scenario conflict documented by Kie.
        """
        if not self.kie_key:
            return {"success": False, "error": "KIE_AI_API_KEY is not configured"}

        normalized_prompt = str(prompt or "").strip()
        if not normalized_prompt:
            return {"success": False, "error": "Prompt is required for Seedance 2.5"}
        if len(normalized_prompt) > self.MAX_PROMPT_LENGTH:
            normalized_prompt = normalized_prompt[: self.MAX_PROMPT_LENGTH]

        try:
            normalized_duration = int(duration)
        except (TypeError, ValueError):
            normalized_duration = 5
        if normalized_duration not in self.ALLOWED_DURATIONS:
            return {
                "success": False,
                "error": f"Unsupported Seedance 2.5 duration: {normalized_duration}",
            }

        normalized_ratio = str(aspect_ratio or "16:9").strip()
        if normalized_ratio not in self.ALLOWED_RATIOS:
            normalized_ratio = "16:9"

        normalized_resolution = str(resolution or "720p").strip().lower()
        if normalized_resolution not in self.ALLOWED_RESOLUTIONS:
            normalized_resolution = "720p"

        image_urls = [str(url).strip() for url in (reference_image_urls or []) if str(url).strip()]
        video_urls = [str(url).strip() for url in (reference_video_urls or []) if str(url).strip()]
        audio_urls = [str(url).strip() for url in (reference_audio_urls or []) if str(url).strip()]
        image_urls = image_urls[: self.MAX_REFERENCE_IMAGES]
        video_urls = video_urls[: self.MAX_REFERENCE_VIDEOS]
        audio_urls = audio_urls[: self.MAX_REFERENCE_AUDIO]

        input_data: dict[str, Any] = {
            "prompt": normalized_prompt,
            "return_last_frame": bool(return_last_frame),
            "generate_audio": bool(generate_audio),
            "resolution": normalized_resolution,
            "aspect_ratio": normalized_ratio,
            "duration": normalized_duration,
        }
        if image_urls:
            input_data["reference_image_urls"] = image_urls
        if video_urls:
            input_data["reference_video_urls"] = video_urls
        if audio_urls:
            input_data["reference_audio_urls"] = audio_urls

        payload: dict[str, Any] = {
            "model": self.MODEL_NAME,
            "input": input_data,
        }
        if callBackUrl:
            payload["callBackUrl"] = callBackUrl

        logger.info(
            "Seedance 2.5 request: duration=%ss ratio=%s resolution=%s refs(image=%s,video=%s,audio=%s) audio=%s",
            normalized_duration,
            normalized_ratio,
            normalized_resolution,
            len(image_urls),
            len(video_urls),
            len(audio_urls),
            bool(generate_audio),
        )
        return await self._kie_post("/api/v1/jobs/createTask", payload)


seedance_25_service = Seedance25Service(kie_key=config.KIE_AI_API_KEY)
