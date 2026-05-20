"""Bytedance Seedance 2.0 service via Kie.ai unified jobs API."""

import logging
from typing import Any, Dict, List, Optional

from bot.config import config
from bot.services.kling_service import KlingService

logger = logging.getLogger(__name__)


class SeedanceService(KlingService):
    """Wrapper for Bytedance Seedance 2.0 on Kie.ai."""

    MODEL_NAME = "bytedance/seedance-2"
    SUPPORTED_RATIOS = {"16:9", "9:16", "1:1"}
    SUPPORTED_RESOLUTIONS = {"480p", "720p", "1080p"}
    MAX_REFERENCE_IMAGES = 9
    MAX_REFERENCE_VIDEOS = 3
    MAX_REFERENCE_AUDIO = 1

    async def generate_video(
        self,
        *,
        prompt: str,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        resolution: str = "720p",
        first_frame_url: Optional[str] = None,
        last_frame_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        reference_video_urls: Optional[List[str]] = None,
        reference_audio_urls: Optional[List[str]] = None,
        return_last_frame: bool = False,
        generate_audio: bool = True,
        web_search: bool = False,
        callBackUrl: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not prompt or not prompt.strip():
            return self._build_error("prompt_required", "Prompt is required")

        reference_image_urls = [
            str(url).strip()
            for url in (reference_image_urls or [])
            if str(url).strip()
        ]
        reference_video_urls = [
            str(url).strip()
            for url in (reference_video_urls or [])
            if str(url).strip()
        ]
        reference_audio_urls = [
            str(url).strip()
            for url in (reference_audio_urls or [])
            if str(url).strip()
        ]

        has_first_last = bool(first_frame_url or last_frame_url)
        has_multimodal_refs = bool(
            reference_image_urls or reference_video_urls or reference_audio_urls
        )
        if has_first_last and has_multimodal_refs:
            return self._build_error(
                "invalid_seedance_scenario",
                "Seedance 2.0 does not allow first/last-frame inputs together with multimodal references in one task.",
            )

        input_data: Dict[str, Any] = {
            "prompt": prompt[:4000],
            "duration": max(5, min(int(duration), 15)),
            "aspect_ratio": (
                aspect_ratio if aspect_ratio in self.SUPPORTED_RATIOS else "16:9"
            ),
            "resolution": (
                resolution if resolution in self.SUPPORTED_RESOLUTIONS else "720p"
            ),
            "return_last_frame": bool(return_last_frame),
            "generate_audio": bool(generate_audio),
            "web_search": bool(web_search),
        }

        if first_frame_url:
            input_data["first_frame_url"] = first_frame_url
        if last_frame_url:
            input_data["last_frame_url"] = last_frame_url
        if reference_image_urls:
            input_data["reference_image_urls"] = reference_image_urls[
                : self.MAX_REFERENCE_IMAGES
            ]
        if reference_video_urls:
            input_data["reference_video_urls"] = reference_video_urls[
                : self.MAX_REFERENCE_VIDEOS
            ]
        if reference_audio_urls:
            input_data["reference_audio_urls"] = reference_audio_urls[
                : self.MAX_REFERENCE_AUDIO
            ]

        payload: Dict[str, Any] = {
            "model": self.MODEL_NAME,
            "input": input_data,
        }
        if callBackUrl:
            payload["callBackUrl"] = callBackUrl

        logger.info(
            "Seedance create_task: duration=%s ratio=%s resolution=%s first_last=%s ref_images=%s ref_videos=%s ref_audio=%s",
            input_data["duration"],
            input_data["aspect_ratio"],
            input_data["resolution"],
            bool(first_frame_url or last_frame_url),
            len(reference_image_urls),
            len(reference_video_urls),
            len(reference_audio_urls),
        )
        return await self._kie_post(self.CREATE_TASK_ENDPOINT, payload)


seedance_service = SeedanceService(kie_key=config.KIE_AI_API_KEY)
