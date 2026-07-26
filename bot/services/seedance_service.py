"""Bytedance Seedance 2.0 service via Kie.ai unified jobs API."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from bot.config import config
from bot.services.kie_file_upload_service import kie_file_upload_service
from bot.services.kling_service import KlingService
from bot.services.media_input_utils import image_sources_to_provider_safe_png_urls

logger = logging.getLogger(__name__)


def _clean_unique_urls(values: Iterable[str] | None) -> List[str]:
    """Normalize reference URLs without changing their user supplied order."""
    cleaned: List[str] = []
    seen: set[str] = set()
    for value in values or []:
        url = str(value or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        cleaned.append(url)
    return cleaned


def _with_seedance_identity_guidance(
    prompt: str,
    *,
    has_first_frame: bool,
    reference_image_count: int,
    reference_video_count: int,
) -> str:
    """Assign explicit roles to Seedance image and video references.

    Seedance accepts both media types, but without a strict role description it
    may preserve the actor from the motion video and borrow only attributes from
    the identity image. The guidance keeps image #1 authoritative for identity
    and limits video references to choreography, timing and camera motion.
    """
    if not (has_first_frame or reference_image_count):
        return prompt

    guidance_parts = [
        "IDENTITY AND REFERENCE ROLE LOCK:",
        "The person visible in every generated shot must be the same recognizable person from the primary uploaded image.",
        "Preserve that person's face geometry, eyes, nose, lips, skin tone, hairstyle, body proportions, clothing and distinctive details.",
        "Re-render the performer as that person; do not keep the actor from a reference video and merely recolor hair or replace clothing.",
        "Do not replace the primary person with a different actor, lookalike or invented character.",
        "Do not add extra people unless the user explicitly requests them.",
    ]
    if has_first_frame:
        guidance_parts.append(
            "The first-frame image is the exact visual and identity anchor for the generated video."
        )
    elif reference_image_count:
        guidance_parts.extend(
            [
                "Reference Image 1 (@Image1) is the PRIMARY PERSON AND IDENTITY source.",
                "Any later reference images are secondary cues for outfit, styling, scene or details unless the user states otherwise.",
            ]
        )
    if reference_video_count:
        guidance_parts.extend(
            [
                "Reference Video 1 (@Video1), and any later videos, provide MOTION ONLY: choreography, pose sequence, timing, camera movement and atmosphere.",
                "Do not preserve or copy the face, body identity, hair or clothing of performers visible in the reference videos.",
            ]
        )

    guidance = "\n".join(guidance_parts)
    return f"{prompt.strip()}\n\n{guidance}" if prompt.strip() else guidance


class SeedanceService(KlingService):
    """Wrapper for Bytedance Seedance 2.0 on Kie.ai."""

    MODEL_NAME = "bytedance/seedance-2"
    SUPPORTED_RATIOS = {
        "1:1",
        "4:3",
        "3:4",
        "16:9",
        "9:16",
        "21:9",
        "adaptive",
    }
    SUPPORTED_RESOLUTIONS = {"480p", "720p", "1080p", "4k"}
    MAX_REFERENCE_IMAGES = 9
    MAX_REFERENCE_VIDEOS = 3
    MAX_REFERENCE_AUDIO = 3
    MIN_DURATION = 4
    MAX_DURATION = 15
    MAX_PROMPT_LENGTH = 20_000

    async def _prepare_image_urls(
        self, image_urls: List[str]
    ) -> tuple[List[str], List[str], List[str]]:
        """Prepare local image inputs before Seedance receives them."""
        if not image_urls:
            return [], [], []

        safe_image_urls = image_sources_to_provider_safe_png_urls(image_urls)
        uploaded_image_urls = await kie_file_upload_service.upload_local_image_sources(
            safe_image_urls
        )

        effective_urls: List[str] = []
        missing_urls: List[str] = []
        failed_upload_urls: List[str] = []
        for original_url, uploaded_url in zip(image_urls, uploaded_image_urls):
            uploaded = str(uploaded_url or "").strip()
            if not uploaded:
                missing_urls.append(original_url)
                continue
            effective_urls.append(uploaded)

        if len(uploaded_image_urls) < len(image_urls):
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

        first_frame_url = str(first_frame_url or "").strip() or None
        last_frame_url = str(last_frame_url or "").strip() or None
        reference_image_urls = _clean_unique_urls(reference_image_urls)
        reference_video_urls = _clean_unique_urls(reference_video_urls)
        reference_audio_urls = _clean_unique_urls(reference_audio_urls)

        # Old repeat payloads could contain the same image in both first_frame_url
        # and reference_image_urls. It is one first-frame scenario, not a mixed
        # scenario, so remove exact duplicates before enforcing exclusivity.
        frame_urls = {url for url in (first_frame_url, last_frame_url) if url}
        if frame_urls and reference_image_urls:
            reference_image_urls = [
                url for url in reference_image_urls if url not in frame_urls
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
            frame_image_urls.append(first_frame_url)
        if last_frame_url:
            frame_fields.append("last_frame_url")
            frame_image_urls.append(last_frame_url)

        limited_reference_image_urls = reference_image_urls[
            : self.MAX_REFERENCE_IMAGES
        ]
        limited_reference_video_urls = reference_video_urls[
            : self.MAX_REFERENCE_VIDEOS
        ]
        limited_reference_audio_urls = reference_audio_urls[
            : self.MAX_REFERENCE_AUDIO
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
            reference_video_count=len(limited_reference_video_urls),
        )

        try:
            normalized_duration = int(duration)
        except (TypeError, ValueError):
            normalized_duration = 5

        input_data: Dict[str, Any] = {
            "prompt": conditioned_prompt[: self.MAX_PROMPT_LENGTH],
            "duration": max(
                self.MIN_DURATION,
                min(normalized_duration, self.MAX_DURATION),
            ),
            "aspect_ratio": (
                aspect_ratio if aspect_ratio in self.SUPPORTED_RATIOS else "16:9"
            ),
            "resolution": (
                resolution if resolution in self.SUPPORTED_RESOLUTIONS else "720p"
            ),
            "generate_audio": bool(generate_audio),
            "web_search": bool(web_search),
        }
        if return_last_frame:
            input_data["return_last_frame"] = True

        if prepared_frames.get("first_frame_url"):
            input_data["first_frame_url"] = prepared_frames["first_frame_url"]
        if prepared_frames.get("last_frame_url"):
            input_data["last_frame_url"] = prepared_frames["last_frame_url"]
        if prepared_reference_image_urls:
            input_data["reference_image_urls"] = prepared_reference_image_urls
        if limited_reference_video_urls:
            input_data["reference_video_urls"] = limited_reference_video_urls
        if limited_reference_audio_urls:
            input_data["reference_audio_urls"] = limited_reference_audio_urls

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
            len(prepared_reference_image_urls),
            len(limited_reference_video_urls),
            len(limited_reference_audio_urls),
        )
        return await self._kie_post(self.CREATE_TASK_ENDPOINT, payload)


seedance_service = SeedanceService(kie_key=config.KIE_AI_API_KEY)
