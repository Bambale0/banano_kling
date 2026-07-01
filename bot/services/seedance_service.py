"""Bytedance Seedance 2.0 service via Kie.ai unified jobs API."""

import logging
from typing import Any, Dict, List, Optional

from bot.config import config
from bot.services.kie_file_upload_service import kie_file_upload_service
from bot.services.kling_service import KlingService
from bot.services.media_input_utils import (
    image_sources_to_provider_safe_png_urls,
    is_local_upload_source,
)

logger = logging.getLogger(__name__)


def _with_seedance_identity_guidance(
    prompt: str,
    *,
    has_first_frame: bool,
    reference_image_count: int,
    reference_video_count: int,
) -> str:
    """Add a compact identity lock for image-conditioned Seedance tasks."""
    if not (has_first_frame or reference_image_count):
        return prompt

    guidance_parts = [
        "IDENTITY / SOURCE LOCK:",
        "Use the uploaded source image as the primary identity and character reference.",
        "Preserve the same recognizable person: face geometry, eyes, nose, lips, skin tone, hair, body proportions, outfit, and distinctive marks.",
        "Do not replace the person with a different actor, lookalike, or invented character.",
        "Do not add extra people unless the user explicitly asks for multiple people.",
    ]
    if has_first_frame:
        guidance_parts.append(
            "The first-frame image is the exact starting frame and must anchor the video."
        )
    elif reference_image_count:
        guidance_parts.append(
            "The first reference image is the main subject identity; later references are secondary style, pose, scene, or motion cues."
        )
    if reference_video_count:
        guidance_parts.append(
            "Use video references for motion and atmosphere only; do not copy unrelated identities from them."
        )

    guidance = "\n".join(guidance_parts)
    return f"{prompt.strip()}\n\n{guidance}" if prompt.strip() else guidance


class SeedanceService(KlingService):
    """Wrapper for Bytedance Seedance 2.0 on Kie.ai."""

    MODEL_NAME = "bytedance/seedance-2"
    SUPPORTED_RATIOS = {"16:9", "9:16", "1:1"}
    SUPPORTED_RESOLUTIONS = {"480p", "720p", "1080p"}
    MAX_REFERENCE_IMAGES = 9
    MAX_REFERENCE_VIDEOS = 3
    MAX_REFERENCE_AUDIO = 1

    async def _prepare_image_urls(
        self, image_urls: List[str]
    ) -> tuple[List[str], List[str], List[str]]:
        """Upload local image inputs to KIE's file store before Seedance sees them."""
        if not image_urls:
            return [], [], []

        safe_image_urls = image_sources_to_provider_safe_png_urls(image_urls)
        uploaded_image_urls = await kie_file_upload_service.upload_local_image_sources(
            safe_image_urls
        )

        effective_urls: List[str] = []
        missing_urls: List[str] = []
        failed_upload_urls: List[str] = []
        for original_url, safe_url, uploaded_url in zip(
            image_urls, safe_image_urls, uploaded_image_urls
        ):
            uploaded = str(uploaded_url or "").strip()
            if not uploaded:
                missing_urls.append(original_url)
                continue
            # Stable public /uploads PNG URLs are valid provider inputs for Seedance.
            # Do not mark them as failed just because they still point to this app host.
            effective_urls.append(uploaded)

        if len(uploaded_image_urls) < len(safe_image_urls):
            missing_urls.extend(image_urls[len(uploaded_image_urls) :])

        return effective_urls, missing_urls, failed_upload_urls

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

        frame_fields: List[str] = []
        frame_image_urls: List[str] = []
        if first_frame_url:
            frame_fields.append("first_frame_url")
            frame_image_urls.append(str(first_frame_url).strip())
        if last_frame_url:
            frame_fields.append("last_frame_url")
            frame_image_urls.append(str(last_frame_url).strip())

        limited_reference_image_urls = reference_image_urls[
            : self.MAX_REFERENCE_IMAGES
        ]
        image_inputs = [*frame_image_urls, *limited_reference_image_urls]
        prepared_image_urls, missing_image_urls, failed_upload_urls = (
            await self._prepare_image_urls(image_inputs)
        )
        if missing_image_urls:
            logger.warning(
                "Seedance create_task blocked: missing local image refs=%s sample=%s",
                len(missing_image_urls),
                missing_image_urls[:3],
            )
            return self._build_error(
                "missing_local_references",
                "Один или несколько старых фото-референсов уже недоступны. Загрузите фото заново.",
            )
        if failed_upload_urls:
            logger.warning(
                "Seedance create_task blocked: local image upload failed refs=%s sample=%s",
                len(failed_upload_urls),
                failed_upload_urls[:3],
            )
            return self._build_error(
                "local_image_upload_failed",
                "Не удалось подготовить фото-референсы для видео. Загрузите фото заново и попробуйте ещё раз.",
            )
        if len(prepared_image_urls) != len(image_inputs):
            logger.warning(
                "Seedance create_task blocked: prepared image count mismatch original=%s prepared=%s",
                len(image_inputs),
                len(prepared_image_urls),
            )
            return self._build_error(
                "invalid_image_references",
                "Не удалось подготовить фото-референсы для видео. Попробуйте ещё раз.",
            )

        prepared_frames = dict(
            zip(frame_fields, prepared_image_urls[: len(frame_image_urls)])
        )
        prepared_reference_image_urls = prepared_image_urls[len(frame_image_urls) :]

        conditioned_prompt = _with_seedance_identity_guidance(
            prompt,
            has_first_frame=bool(prepared_frames.get("first_frame_url")),
            reference_image_count=len(prepared_reference_image_urls),
            reference_video_count=len(reference_video_urls),
        )

        input_data: Dict[str, Any] = {
            "prompt": conditioned_prompt[:4000],
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

        if prepared_frames.get("first_frame_url"):
            input_data["first_frame_url"] = prepared_frames["first_frame_url"]
        if prepared_frames.get("last_frame_url"):
            input_data["last_frame_url"] = prepared_frames["last_frame_url"]
        if prepared_reference_image_urls:
            input_data["reference_image_urls"] = prepared_reference_image_urls
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
            "Seedance create_task: duration=%s ratio=%s resolution=%s first_last=%s ref_images=%s ref_videos=%s ref_audio=%s image_transport=%s",
            input_data["duration"],
            input_data["aspect_ratio"],
            input_data["resolution"],
            bool(first_frame_url or last_frame_url),
            len(prepared_reference_image_urls),
            len(reference_video_urls),
            len(reference_audio_urls),
            (
                "kie_file_upload_urls"
                if prepared_image_urls != image_inputs
                else "public_urls"
            ),
        )
        return await self._kie_post(self.CREATE_TASK_ENDPOINT, payload)


seedance_service = SeedanceService(kie_key=config.KIE_AI_API_KEY)
