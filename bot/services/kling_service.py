"""
Kling API Service - Реализация всех методов Freepik API для Kling 2.6 и Kling 3

Документация Kling 2.6: https://docs.freepik.com/apis/freepik/ai/kling-v2-6
Документация Kling 3: https://docs.freepik.com/apis/freepik/ai/kling-v3

Kling 2.6 Endpoints:
- POST /v1/ai/image-to-video/kling-v2-6-pro - Kling 2.6 Pro (text/image to video)
- GET /v1/ai/image-to-video/kling-v2-6 - List Kling 2.6 tasks
- GET /v1/ai/image-to-video/kling-v2-6/{task_id} - Get Kling 2.6 task status
- POST /v1/ai/video/kling-v2-6-motion-control-pro - Motion control Pro
- POST /v1/ai/video/kling-v2-6-motion-control-std - Motion control Standard

Kling 3 Endpoints:
- POST /v1/ai/video/kling-v3-pro - Generate video Kling 3 Pro
- POST /v1/ai/video/kling-v3-std - Generate video Kling 3 Standard
- GET /v1/ai/video/kling-v3 - List all Kling 3 tasks
- GET /v1/ai/video/kling-v3/{task_id} - Get task status by ID
- POST /v1/ai/video/kling-v3-omni-pro - Kling 3 Omni Pro (text/image to video)
- POST /v1/ai/video/kling-v3-omni-std - Kling 3 Omni Standard (text/image to video)
- GET /v1/ai/video/kling-v3-omni - List all Kling 3 Omni tasks
- GET /v1/ai/video/kling-v3-omni/{task_id} - Get Omni task status
- POST /v1/ai/reference-to-video/kling-v3-omni-pro - Video-to-video Pro
- POST /v1/ai/reference-to-video/kling-v3-omni-std - Video-to-video Standard
- GET /v1/ai/reference-to-video/kling-v3-omni - List R2V tasks
- GET /v1/ai/reference-to-video/kling-v3-omni/{task_id} - Get R2V task status
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


class KlingService:
    """Сервис для работы с Kling API через Freepik (поддерживает Kling 2.6 и Kling 3)"""

    # API Endpoints (without /v1 prefix - it's already in base_url)
    ENDPOINTS = {
        # Kling 2.6 Pro (image-to-video)
        "v26_pro": "/ai/image-to-video/kling-v2-6-pro",
        "v26_tasks": "/ai/image-to-video/kling-v2-6",
        # Kling 2.6 Motion Control
        "v26_motion_pro": "/ai/video/kling-v2-6-motion-control-pro",
        "v26_motion_std": "/ai/video/kling-v2-6-motion-control-std",
        # Kling 3 Pro/Standard
        "v3_pro": "/ai/video/kling-v3-pro",
        "v3_std": "/ai/video/kling-v3-std",
        "v3_tasks": "/ai/video/kling-v3",
        # Kling 3 Omni
        "v3_omni_pro": "/ai/video/kling-v3-omni-pro",
        "v3_omni_std": "/ai/video/kling-v3-omni-std",
        "v3_omni_tasks": "/ai/video/kling-v3-omni",
        # Kling 3 Omni Reference-to-Video
        "v3_omni_pro_r2v": "/ai/reference-to-video/kling-v3-omni-pro",
        "v3_omni_std_r2v": "/ai/reference-to-video/kling-v3-omni-std",
        "v3_omni_r2v_tasks": "/ai/reference-to-video/kling-v3-omni",
    }

    # Valid parameters
    ASPECT_RATIOS = ["16:9", "9:16", "1:1"]
    # Kling 2.6 supports different aspect ratios
    ASPECT_RATIOS_V26 = ["widescreen_16_9", "social_story_9_16", "square_1_1"]
    # Kling 2.6 only supports 5 and 10 second durations
    DURATIONS_V26 = ["5", "10"]
    # Kling 3 supports 3-15 seconds
    DURATIONS = ["3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15"]

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "x-freepik-api-key": api_key,
            "Content-Type": "application/json",
        }

    # =========================================================================
    # Kling 2.6 Pro Methods (Text-to-Video and Image-to-Video)
    # =========================================================================

    async def generate_video_v26_pro(
        self,
        prompt: str,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        webhook_url: Optional[str] = None,
        image: Optional[str] = None,  # Base64 or URL for image-to-video
        negative_prompt: Optional[str] = None,
        cfg_scale: float = 0.5,
        generate_audio: bool = True,
    ) -> Optional[Dict]:
        """
        POST /v1/ai/image-to-video/kling-v2-6-pro

        Generate AI video using Kling 2.6 Pro with text-to-video or image-to-video capabilities.

        Args:
            prompt: Text prompt describing the video (max 2500 chars)
            duration: Duration in seconds (5 or 10)
            aspect_ratio: Video ratio - "widescreen_16_9", "social_story_9_16", "square_1_1"
            webhook_url: Optional callback URL for async notifications
            image: Reference image (Base64 or URL) for image-to-video. Must be >300x300px, <10MB
            negative_prompt: Undesired elements to avoid (max 2500 chars)
            cfg_scale: Prompt adherence (0-1, default 0.5)
            generate_audio: Whether to generate audio for the video

        Returns:
            Dict с task_id или None при ошибке
        """
        endpoint = self.ENDPOINTS["v26_pro"]
        url = f"{self.base_url}{endpoint}"

        # Validate duration - Kling 2.6 only supports 5 and 10 seconds
        duration = 10 if duration > 5 else 5

        # Convert aspect ratio to Kling 2.6 format
        aspect_ratio_map = {
            "16:9": "widescreen_16_9",
            "9:16": "social_story_9_16",
            "1:1": "square_1_1",
        }
        v26_aspect = aspect_ratio_map.get(aspect_ratio, "widescreen_16_9")

        payload = {
            "prompt": prompt[:2500],  # Max 2500 chars
            "duration": str(duration),
            "aspect_ratio": v26_aspect,
            "cfg_scale": min(max(cfg_scale, 0), 1),
            "generate_audio": generate_audio,
        }

        if webhook_url:
            payload["webhook_url"] = webhook_url

        if image:
            payload["image"] = image

        if negative_prompt:
            payload["negative_prompt"] = negative_prompt[:2500]

        logger.info(
            f"Kling 2.6 Pro request: prompt={prompt[:50]}..., duration={duration}, aspect={v26_aspect}, has_image={bool(image)}"
        )

        return await self._post_request(url, payload)

    async def list_v26_tasks(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> Optional[Dict]:
        """
        GET /v1/ai/image-to-video/kling-v2-6

        Retrieve the list of all Kling 2.6 video generation tasks.

        Args:
            page: Page number (1-indexed)
            page_size: Number of items per page (max 100)

        Returns:
            Dict с списком задач
        """
        endpoint = self.ENDPOINTS["v26_tasks"]
        url = f"{self.base_url}{endpoint}"

        params = {
            "page": max(page, 1),
            "page_size": min(max(page_size, 1), 100),
        }

        logger.info(f"Kling 2.6 list tasks: page={page}, page_size={page_size}")

        return await self._get_request(url, params)

    async def get_v26_task_status(self, task_id: str) -> Optional[Dict]:
        """
        GET /v1/ai/image-to-video/kling-v2-6/{task_id}

        Retrieve the status and result of a specific Kling 2.6 video generation task.

        Args:
            task_id: ID of the task

        Returns:
            Dict с статусом задачи и результатом
        """
        endpoint = self.ENDPOINTS["v26_tasks"]
        url = f"{self.base_url}{endpoint}/{task_id}"

        logger.info(f"Kling 2.6 get task status: {task_id}")

        return await self._get_request(url)

    # =========================================================================
    # Kling 2.6 Motion Control Methods
    # =========================================================================

    async def generate_motion_control_pro(
        self,
        image_url: str,
        video_url: str,
        prompt: Optional[str] = None,
        webhook_url: Optional[str] = None,
        character_orientation: str = "video",
        cfg_scale: float = 0.5,
    ) -> Optional[Dict]:
        """
        POST /v1/ai/video/kling-v2-6-motion-control-pro

        Transfer motion from a reference video to a character image using Kling 2.6 Pro.
        The model preserves the character's appearance while applying motion patterns from the reference video.

        Args:
            image_url: URL of the character/reference image (min 300x300px, max 10MB, JPG/PNG/WEBP)
            video_url: URL of the reference video (3-30s, MP4/MOV/WEBM/M4V)
            prompt: Optional text prompt to guide motion transfer (max 2500 chars)
            webhook_url: Optional callback URL for async notifications
            character_orientation: "video" (matches video orientation, max 30s) or "image" (matches image orientation, max 10s)
            cfg_scale: Prompt adherence (0-1, default 0.5)

        Returns:
            Dict с task_id или None при ошибке
        """
        endpoint = self.ENDPOINTS["v26_motion_pro"]
        url = f"{self.base_url}{endpoint}"

        payload = {
            "image_url": image_url,
            "video_url": video_url,
            "character_orientation": (
                character_orientation
                if character_orientation in ["video", "image"]
                else "video"
            ),
            "cfg_scale": min(max(cfg_scale, 0), 1),
        }

        if webhook_url:
            payload["webhook_url"] = webhook_url

        if prompt:
            payload["prompt"] = prompt[:2500]

        logger.info(
            f"Kling 2.6 Motion Control Pro: image_url={image_url[:50]}..., video_url={video_url[:50]}..."
        )

        return await self._post_request(url, payload)

    async def generate_motion_control_std(
        self,
        image_url: str,
        video_url: str,
        prompt: Optional[str] = None,
        webhook_url: Optional[str] = None,
        character_orientation: str = "video",
        cfg_scale: float = 0.5,
    ) -> Optional[Dict]:
        """
        POST /v1/ai/video/kling-v2-6-motion-control-std

        Transfer motion from a reference video to a character image using Kling 2.6 Standard.
        Standard mode offers faster generation at slightly lower quality.

        Args:
            image_url: URL of the character/reference image (min 300x300px, max 10MB, JPG/PNG/WEBP)
            video_url: URL of the reference video (3-30s, MP4/MOV/WEBM/M4V)
            prompt: Optional text prompt to guide motion transfer (max 2500 chars)
            webhook_url: Optional callback URL for async notifications
            character_orientation: "video" or "image"
            cfg_scale: Prompt adherence (0-1, default 0.5)

        Returns:
            Dict с task_id или None при ошибке
        """
        endpoint = self.ENDPOINTS["v26_motion_std"]
        url = f"{self.base_url}{endpoint}"

        payload = {
            "image_url": image_url,
            "video_url": video_url,
            "character_orientation": (
                character_orientation
                if character_orientation in ["video", "image"]
                else "video"
            ),
            "cfg_scale": min(max(cfg_scale, 0), 1),
        }

        if webhook_url:
            payload["webhook_url"] = webhook_url

        if prompt:
            payload["prompt"] = prompt[:2500]

        logger.info(
            f"Kling 2.6 Motion Control Std: image_url={image_url[:50]}..., video_url={video_url[:50]}..."
        )

        return await self._post_request(url, payload)

    # =========================================================================
    # Kling 3 Pro/Standard Methods
    # =========================================================================

    async def generate_video_pro(
        self,
        prompt: str,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        webhook_url: Optional[str] = None,
        start_image_url: Optional[str] = None,
        end_image_url: Optional[str] = None,
        elements: Optional[List[Dict]] = None,
        negative_prompt: Optional[str] = "blur, distort, and low quality",
        cfg_scale: float = 0.5,
        generate_audio: bool = True,
        voice_ids: Optional[List[str]] = None,
        multi_prompt: Optional[List[Dict]] = None,
        shot_type: str = "customize",
        multi_shot: bool = False,
    ) -> Optional[Dict]:
        """
        POST /v1/ai/video/kling-v3-pro

        Generate AI video using Kling 3 Pro with text-to-video or image-to-video capabilities.

        Args:
            prompt: Text prompt describing the video (max 2500 chars)
            duration: Duration in seconds (3-15)
            aspect_ratio: Video ratio - "16:9", "9:16", "1:1"
            webhook_url: Optional callback URL for async notifications
            start_image_url: First frame image URL for I2V
            end_image_url: Last frame image URL for I2V
            elements: List of elements for consistent identity
            negative_prompt: Undesired elements to avoid
            cfg_scale: Prompt adherence (0-1, default 0.5)
            generate_audio: Whether to generate native audio
            voice_ids: Custom voice identifiers (max 2)
            multi_prompt: Multi-shot prompts with durations (max 6 scenes)
            shot_type: "customize" or "intelligent"
            multi_shot: Enable multi-shot mode for multi-scene videos

        Returns:
            Dict с task_id или None при ошибке
        """
        endpoint = self.ENDPOINTS["v3_pro"]
        url = f"{self.base_url}{endpoint}"

        payload = self._build_v3_payload(
            prompt=prompt,
            duration=duration,
            aspect_ratio=aspect_ratio,
            webhook_url=webhook_url,
            start_image_url=start_image_url,
            end_image_url=end_image_url,
            elements=elements,
            negative_prompt=negative_prompt,
            cfg_scale=cfg_scale,
            generate_audio=generate_audio,
            voice_ids=voice_ids,
            multi_prompt=multi_prompt,
            shot_type=shot_type,
            multi_shot=multi_shot,
        )

        logger.info(
            f"Kling 3 Pro request: prompt={prompt[:50]}..., duration={duration}, aspect={aspect_ratio}"
        )

        return await self._post_request(url, payload)

    async def generate_video_std(
        self,
        prompt: str,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        webhook_url: Optional[str] = None,
        start_image_url: Optional[str] = None,
        end_image_url: Optional[str] = None,
        elements: Optional[List[Dict]] = None,
        negative_prompt: Optional[str] = "blur, distort, and low quality",
        cfg_scale: float = 0.5,
        generate_audio: bool = True,
        voice_ids: Optional[List[str]] = None,
        multi_prompt: Optional[List[Dict]] = None,
        shot_type: str = "customize",
        multi_shot: bool = False,
    ) -> Optional[Dict]:
        """
        POST /v1/ai/video/kling-v3-std

        Generate AI video using Kling 3 Standard with text-to-video or image-to-video capabilities.
        Standard mode offers faster generation at slightly lower quality.

        Args:
            prompt: Text prompt describing the video (max 2500 chars)
            duration: Duration in seconds (3-15)
            aspect_ratio: Video ratio - "16:9", "9:16", "1:1"
            webhook_url: Optional callback URL for async notifications
            start_image_url: First frame image URL for I2V
            end_image_url: Last frame image URL for I2V
            elements: List of elements for consistent identity
            negative_prompt: Undesired elements to avoid
            cfg_scale: Prompt adherence (0-1, default 0.5)
            generate_audio: Whether to generate native audio
            voice_ids: Custom voice identifiers (max 2)
            multi_prompt: Multi-shot prompts with durations (max 6 scenes)
            shot_type: "customize" or "intelligent"
            multi_shot: Enable multi-shot mode for multi-scene videos

        Returns:
            Dict с task_id или None при ошибке
        """
        endpoint = self.ENDPOINTS["v3_std"]
        url = f"{self.base_url}{endpoint}"

        payload = self._build_v3_payload(
            prompt=prompt,
            duration=duration,
            aspect_ratio=aspect_ratio,
            webhook_url=webhook_url,
            start_image_url=start_image_url,
            end_image_url=end_image_url,
            elements=elements,
            negative_prompt=negative_prompt,
            cfg_scale=cfg_scale,
            generate_audio=generate_audio,
            voice_ids=voice_ids,
            multi_prompt=multi_prompt,
            shot_type=shot_type,
            multi_shot=multi_shot,
        )

        logger.info(
            f"Kling 3 Std request: prompt={prompt[:50]}..., duration={duration}, aspect={aspect_ratio}, start_image={start_image_url is not None}, elements={elements is not None}"
        )

        return await self._post_request(url, payload)

    def _build_v3_payload(
        self,
        prompt: str,
        duration: int,
        aspect_ratio: str,
        webhook_url: Optional[str],
        start_image_url: Optional[str],
        end_image_url: Optional[str],
        elements: Optional[List[Dict]],
        negative_prompt: Optional[str],
        cfg_scale: float,
        generate_audio: bool,
        voice_ids: Optional[List[str]],
        multi_prompt: Optional[List[Dict]],
        shot_type: str,
        multi_shot: bool = False,
    ) -> Dict:
        """Build payload for Kling v3 Pro/Std request"""
        # Duration должен быть строкой
        duration_str = str(min(max(duration, 3), 15))
        logger.debug(
            f"_build_v3_payload: input_duration={duration}, output_duration_str={duration_str}"
        )

        payload = {
            "prompt": prompt,
            "duration": duration_str,
            "aspect_ratio": (
                aspect_ratio if aspect_ratio in self.ASPECT_RATIOS else "16:9"
            ),
            "cfg_scale": min(max(cfg_scale, 0), 1),  # Kling 3: 0-1 (default 0.5)
            "generate_audio": generate_audio,
        }

        if multi_shot:
            payload["multi_shot"] = True
            payload["shot_type"] = shot_type

        if webhook_url:
            payload["webhook_url"] = webhook_url

        # ПРАВИЛЬНО по документации Kling 3 Pro/Std:
        # Используем start_image_url и end_image_url напрямую (НЕ image_list!)
        if start_image_url:
            payload["start_image_url"] = start_image_url
            logger.info(f"Using start_image_url: {start_image_url[:50]}...")

        if end_image_url:
            payload["end_image_url"] = end_image_url
            logger.info(f"Using end_image_url: {end_image_url[:50]}...")

        # element_list для сохранения персонажей/стиля
        if elements:
            element_list = []
            for elem in elements:
                if isinstance(elem, dict):
                    # Проверяем правильный формат
                    if "reference_image_urls" in elem or "frontal_image_url" in elem:
                        element_list.append(elem)
                    else:
                        # Конвертация из старого формата
                        element_list.append(
                            {
                                "reference_image_urls": elem.get(
                                    "reference_image_urls", []
                                ),
                                "frontal_image_url": elem.get(
                                    "frontal_image_url", elem.get("image_url")
                                ),
                            }
                        )
            if element_list:
                payload["element_list"] = element_list
                logger.info(f"Using element_list with {len(element_list)} elements")

        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        if voice_ids:
            payload["voice_ids"] = voice_ids[:2]  # Max 2

        # ПРАВИЛЬНО: multi_prompt с index (0-5), prompt и duration
        if multi_prompt:
            formatted_multi_prompt = []
            for idx, item in enumerate(multi_prompt):
                if isinstance(item, dict):
                    formatted_multi_prompt.append(
                        {
                            "index": item.get("index", idx),  # index обязателен (0-5)
                            "prompt": item.get("prompt", ""),
                            "duration": str(item.get("duration", 5)),  # Строка!
                        }
                    )
                else:
                    # Если передана строка, используем индекс по порядку
                    formatted_multi_prompt.append(
                        {"index": idx, "prompt": str(item), "duration": "5"}
                    )
            payload["multi_prompt"] = formatted_multi_prompt

        logger.info(f"DEBUG payload: {payload}")
        return payload

    async def list_v3_tasks(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> Optional[Dict]:
        """
        GET /v1/ai/video/kling-v3

        Retrieve the list of all Kling 3 video generation tasks.

        Args:
            page: Page number (1-indexed)
            page_size: Number of items per page (max 100)

        Returns:
            Dict с списком задач
        """
        endpoint = self.ENDPOINTS["v3_tasks"]
        url = f"{self.base_url}{endpoint}"

        params = {
            "page": max(page, 1),
            "page_size": min(max(page_size, 1), 100),
        }

        logger.info(f"Kling 3 list tasks: page={page}, page_size={page_size}")

        return await self._get_request(url, params)

    async def get_v3_task_status(self, task_id: str) -> Optional[Dict]:
        """
        GET /v1/ai/video/kling-v3/{task_id}

        Retrieve the status and result of a specific Kling 3 video generation task.

        Args:
            task_id: ID of the task

        Returns:
            Dict с статусом задачи и результатом
        """
        endpoint = self.ENDPOINTS["v3_tasks"]
        url = f"{self.base_url}{endpoint}/{task_id}"

        logger.info(f"Kling 3 get task status: {task_id}")

        return await self._get_request(url)

    # =========================================================================
    # Kling 3 Omni Methods
    # =========================================================================

    async def generate_video_omni_pro(
        self,
        prompt: str,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        webhook_url: Optional[str] = None,
        start_image_url: Optional[str] = None,
        end_image_url: Optional[str] = None,
        image_url: Optional[str] = None,
        image_urls: Optional[List[str]] = None,
        elements: Optional[List[Dict]] = None,
        generate_audio: bool = True,
        voice_ids: Optional[List[str]] = None,
        multi_prompt: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        """
        POST /v1/ai/video/kling-v3-omni-pro

        Generate AI video using Kling 3 Omni Pro with advanced multi-modal capabilities.
        Supports text-to-video and image-to-video.

        Args:
            prompt: Text prompt describing the video (max 2500 chars)
            duration: Duration in seconds (3-15)
            aspect_ratio: Video ratio - "auto", "16:9", "9:16", "1:1"
            webhook_url: Optional callback URL for async notifications
            start_image_url: First frame image URL for I2V
            end_image_url: Last frame image URL for I2V
            image_url: Start frame image URL (alternative)
            image_urls: Reference images for style guidance (max 4)
            elements: Elements for consistent identity
            generate_audio: Whether to generate native audio
            voice_ids: Custom voice identifiers (max 2)
            multi_prompt: List of prompts for multi-shot (max 6)

        Returns:
            Dict с task_id или None при ошибке
        """
        endpoint = self.ENDPOINTS["v3_omni_pro"]
        url = f"{self.base_url}{endpoint}"

        payload = self._build_omni_payload(
            prompt=prompt,
            duration=duration,
            aspect_ratio=aspect_ratio,
            webhook_url=webhook_url,
            start_image_url=start_image_url,
            end_image_url=end_image_url,
            image_url=image_url,
            image_urls=image_urls,
            elements=elements,
            generate_audio=generate_audio,
            voice_ids=voice_ids,
            multi_prompt=multi_prompt,
        )

        logger.info(
            f"Kling 3 Omni Pro request: prompt={prompt[:50]}..., start_image_url={start_image_url[:50] if start_image_url else 'None'}..., payload_keys={list(payload.keys())}"
        )

        return await self._post_request(url, payload)

    async def generate_video_omni_std(
        self,
        prompt: str,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        webhook_url: Optional[str] = None,
        start_image_url: Optional[str] = None,
        end_image_url: Optional[str] = None,
        image_url: Optional[str] = None,
        image_urls: Optional[List[str]] = None,
        elements: Optional[List[Dict]] = None,
        generate_audio: bool = True,
        voice_ids: Optional[List[str]] = None,
        multi_prompt: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        """
        POST /v1/ai/video/kling-v3-omni-std

        Generate AI video using Kling 3 Omni Standard.
        Standard mode offers faster generation at slightly lower quality.
        """
        endpoint = self.ENDPOINTS["v3_omni_std"]
        url = f"{self.base_url}{endpoint}"

        payload = self._build_omni_payload(
            prompt=prompt,
            duration=duration,
            aspect_ratio=aspect_ratio,
            webhook_url=webhook_url,
            start_image_url=start_image_url,
            end_image_url=end_image_url,
            image_url=image_url,
            image_urls=image_urls,
            elements=elements,
            generate_audio=generate_audio,
            voice_ids=voice_ids,
            multi_prompt=multi_prompt,
        )

        logger.info(f"Kling 3 Omni Std request: prompt={prompt[:50]}...")

        return await self._post_request(url, payload)

    def _build_omni_payload(
        self,
        prompt: str,
        duration: int,
        aspect_ratio: str,
        webhook_url: Optional[str],
        start_image_url: Optional[str],
        end_image_url: Optional[str],
        image_url: Optional[str],
        image_urls: Optional[List[str]],
        elements: Optional[List[Dict]],
        generate_audio: bool,
        voice_ids: Optional[List[str]],
        multi_prompt: Optional[List[str]],
    ) -> Dict:
        """Build payload for Kling Omni request"""
        # Handle aspect ratio - Omni supports "auto"
        valid_aspect_ratios = ["auto", "16:9", "9:16", "1:1"]

        payload = {
            "prompt": prompt,
            "duration": str(min(max(duration, 3), 15)),
            "aspect_ratio": (
                aspect_ratio if aspect_ratio in valid_aspect_ratios else "16:9"
            ),
            "generate_audio": generate_audio,
            "shot_type": "customize",
        }

        if webhook_url:
            payload["webhook_url"] = webhook_url

        # ПРАВИЛЬНО по документации Kling 3 Omni: start_image_url и end_image_url напрямую
        if start_image_url:
            payload["start_image_url"] = start_image_url
            logger.info(
                f"Omni payload: added start_image_url={start_image_url[:50]}..."
            )

        if end_image_url:
            payload["end_image_url"] = end_image_url
            logger.info(f"Omni payload: added end_image_url={end_image_url[:50]}...")

        if image_url:
            payload["image_url"] = image_url
            logger.info(f"Omni payload: added image_url={image_url[:50]}...")

        if image_urls:
            payload["image_urls"] = image_urls[:4]  # Max 4 images

        if elements:
            payload["elements"] = elements

        if voice_ids:
            payload["voice_ids"] = voice_ids[:2]  # Max 2 voices

        if multi_prompt:
            payload["multi_prompt"] = multi_prompt[:6]  # Max 6 shots

        logger.info(f"DEBUG payload: {payload}")
        return payload

    async def list_omni_tasks(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> Optional[Dict]:
        """
        GET /v1/ai/video/kling-v3-omni

        Retrieve the list of all Kling 3 Omni video generation tasks.
        """
        endpoint = self.ENDPOINTS["v3_omni_tasks"]
        url = f"{self.base_url}{endpoint}"

        params = {
            "page": max(page, 1),
            "page_size": min(max(page_size, 1), 100),
        }

        logger.info(f"Kling 3 Omni list tasks: page={page}, page_size={page_size}")

        return await self._get_request(url, params)

    async def get_omni_task_status(self, task_id: str) -> Optional[Dict]:
        """
        GET /v1/ai/video/kling-v3-omni/{task_id}

        Retrieve the status and result of a specific Kling 3 Omni task.
        """
        endpoint = self.ENDPOINTS["v3_omni_tasks"]
        url = f"{self.base_url}{endpoint}/{task_id}"

        logger.info(f"Kling 3 Omni get task status: {task_id}")

        return await self._get_request(url)

    # =========================================================================
    # Kling 3 Omni Reference-to-Video Methods
    # =========================================================================

    async def generate_video_omni_pro_r2v(
        self,
        prompt: str,
        video_url: str,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        webhook_url: Optional[str] = None,
        image_url: Optional[str] = None,
        negative_prompt: Optional[str] = "blur, distort, and low quality",
        cfg_scale: float = 0.5,
    ) -> Optional[Dict]:
        """
        POST /v1/ai/reference-to-video/kling-v3-omni-pro

        Generate AI video using Kling 3 Omni Pro with a reference video for motion and style guidance.
        Video-to-video mode requires a video_url parameter.

        Args:
            prompt: Text prompt describing the video (max 2500 chars), use @Video1 to reference the video
            video_url: **Required** URL of the reference video (3-10s, 720-2160px, max 200MB, mp4/mov)
            duration: Duration in seconds (3-15)
            aspect_ratio: Video ratio - "auto", "16:9", "9:16", "1:1"
            webhook_url: Optional callback URL for async notifications
            image_url: Start frame image URL for combined I2V + R2V
            negative_prompt: Undesired elements to avoid
            cfg_scale: Prompt adherence (0-2, default 0.5)

        Returns:
            Dict с task_id или None при ошибке
        """
        endpoint = self.ENDPOINTS["v3_omni_pro_r2v"]
        url = f"{self.base_url}{endpoint}"

        payload = {
            "prompt": prompt,
            "video_url": video_url,  # Required
            "duration": str(min(max(duration, 3), 15)),
            "aspect_ratio": aspect_ratio,
            "cfg_scale": min(max(cfg_scale, 0), 2),
        }

        if webhook_url:
            payload["webhook_url"] = webhook_url

        if image_url:
            payload["image_url"] = image_url

        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        logger.info(f"Kling 3 Omni Pro R2V request: video_url={video_url[:50]}...")

        return await self._post_request(url, payload)

    async def generate_video_omni_std_r2v(
        self,
        prompt: str,
        video_url: str,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        webhook_url: Optional[str] = None,
        image_url: Optional[str] = None,
        negative_prompt: Optional[str] = "blur, distort, and low quality",
        cfg_scale: float = 0.5,
    ) -> Optional[Dict]:
        """
        POST /v1/ai/reference-to-video/kling-v3-omni-std

        Generate AI video using Kling 3 Omni Standard with a reference video.
        Standard mode offers faster generation at slightly lower quality.
        """
        endpoint = self.ENDPOINTS["v3_omni_std_r2v"]
        url = f"{self.base_url}{endpoint}"

        payload = {
            "prompt": prompt,
            "video_url": video_url,  # Required
            "duration": str(min(max(duration, 3), 15)),
            "aspect_ratio": aspect_ratio,
            "cfg_scale": min(max(cfg_scale, 0), 2),
        }

        if webhook_url:
            payload["webhook_url"] = webhook_url

        if image_url:
            payload["image_url"] = image_url

        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        logger.info(f"Kling 3 Omni Std R2V request: video_url={video_url[:50]}...")

        return await self._post_request(url, payload)

    async def list_r2v_tasks(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> Optional[Dict]:
        """
        GET /v1/ai/reference-to-video/kling-v3-omni

        Retrieve the list of all Kling 3 Omni reference-to-video tasks.
        """
        endpoint = self.ENDPOINTS["v3_omni_r2v_tasks"]
        url = f"{self.base_url}{endpoint}"

        params = {
            "page": max(page, 1),
            "page_size": min(max(page_size, 1), 100),
        }

        logger.info(f"Kling 3 Omni R2V list tasks: page={page}, page_size={page_size}")

        return await self._get_request(url, params)

    async def get_r2v_task_status(self, task_id: str) -> Optional[Dict]:
        """
        GET /v1/ai/reference-to-video/kling-v3-omni/{task_id}

        Retrieve the status and result of a specific Kling 3 Omni R2V task.
        """
        endpoint = self.ENDPOINTS["v3_omni_r2v_tasks"]
        url = f"{self.base_url}{endpoint}/{task_id}"

        logger.info(f"Kling 3 Omni R2V get task status: {task_id}")

        return await self._get_request(url)

    # =========================================================================
    # Legacy/Compatibility Methods
    # =========================================================================

    async def generate_video(
        self,
        prompt: str,
        model: str = "v3_std",
        duration: int = 5,
        aspect_ratio: str = "16:9",
        webhook_url: Optional[str] = None,
        image_url: Optional[str] = None,
        video_url: Optional[str] = None,
        end_image_url: Optional[str] = None,
        elements: Optional[List[Dict]] = None,
        negative_prompt: Optional[str] = None,
        cfg_scale: float = 0.5,
        generate_audio: bool = True,
    ) -> Optional[Dict]:
        """
        Универсальный метод для создания видео (обратная совместимость)

        Args:
            prompt: Текстовый промпт
            model: Модель:
                - "v26_pro" - Kling 2.6 Pro (T2V/I2V)
                - "v26_motion_pro" - Kling 2.6 Motion Control Pro
                - "v26_motion_std" - Kling 2.6 Motion Control Std
                - "v3_pro" - Kling 3 Pro
                - "v3_std" - Kling 3 Standard
                - "v3_omni_pro" - Kling 3 Omni Pro (I2V/T2V)
                - "v3_omni_std" - Kling 3 Omni Standard
                - "v3_omni_pro_r2v" - Kling 3 Omni Pro (R2V)
                - "v3_omni_std_r2v" - Kling 3 Omni Standard (R2V)
            duration: Длительность (5 или 10 для v26, 3-15 для v3)
            aspect_ratio: Формат - "16:9", "9:16", "1:1"
            webhook_url: URL для вебхука
            image_url: URL изображения для I2V
            video_url: URL видео для R2V (v3_omni_r2v) или Motion Control (v26_motion)
            end_image_url: URL конечного кадра
            elements: Список элементов
            negative_prompt: Негативный промпт
            cfg_scale: Шкала CFG (0-1)
            generate_audio: Генерация звука

        Returns:
            Dict с task_id или None
        """
        # Map model names to new methods
        model_map = {
            # Kling 2.6
            "v26_pro": self.generate_video_v26_pro,
            "v26_motion_pro": self.generate_motion_control_pro,
            "v26_motion_std": self.generate_motion_control_std,
            # Kling 3
            "v3_pro": self.generate_video_pro,
            "v3_std": self.generate_video_std,
            "v3_omni_pro": self.generate_video_omni_pro,
            "v3_omni_std": self.generate_video_omni_std,
            "v3_omni_pro_r2v": self.generate_video_omni_pro_r2v,
            "v3_omni_std_r2v": self.generate_video_omni_std_r2v,
        }

        method = model_map.get(model)
        if method is None:
            logger.error(f"Unknown model: {model}")
            return None

        # Kling 2.6 Motion Control (requires image_url + video_url)
        if model in ["v26_motion_pro", "v26_motion_std"]:
            if not image_url or not video_url:
                logger.error(
                    "Motion control requires image_url and video_url parameters"
                )
                return None
            return await method(
                image_url=image_url,
                video_url=video_url,
                prompt=prompt,
                webhook_url=webhook_url,
                cfg_scale=cfg_scale,
            )

        # Kling 2.6 Pro (T2V or I2V with image parameter)
        if model == "v26_pro":
            return await method(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
                webhook_url=webhook_url,
                image=image_url,  # Kling 2.6 uses 'image' not 'image_url'
                negative_prompt=negative_prompt,
                cfg_scale=cfg_scale,
                generate_audio=generate_audio,
            )

        # Kling 3 Omni R2V (requires video_url)
        if model in ["v3_omni_pro_r2v", "v3_omni_std_r2v"]:
            if not video_url:
                logger.error("R2V mode requires video_url parameter")
                return None
            return await method(
                prompt=prompt,
                video_url=video_url,
                duration=duration,
                aspect_ratio=aspect_ratio,
                webhook_url=webhook_url,
                image_url=image_url,
                cfg_scale=cfg_scale,
            )

        # Kling 3 Omni (uses start_image_url/end_image_url)
        if model in ["v3_omni_pro", "v3_omni_std"]:
            return await method(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
                webhook_url=webhook_url,
                start_image_url=image_url,
                end_image_url=end_image_url,
                elements=elements,
                generate_audio=generate_audio,
            )

        # Kling 3 Pro/Std
        return await method(
            prompt=prompt,
            duration=duration,
            aspect_ratio=aspect_ratio,
            webhook_url=webhook_url,
            start_image_url=image_url,
            end_image_url=end_image_url,
            elements=elements,
            negative_prompt=negative_prompt,
            cfg_scale=cfg_scale,
            generate_audio=generate_audio,
        )

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        """Проверка статуса задачи (обратная совместимость)"""
        return await self.get_v3_task_status(task_id)

    async def wait_for_completion(
        self, task_id: str, max_attempts: int = 60, delay: int = 5
    ) -> Optional[Dict]:
        """
        Опрос статуса до завершения задачи

        Args:
            task_id: ID задачи
            max_attempts: Максимальное количество попыток
            delay: Задержка между попытками в секундах

        Returns:
            Dict с результатом или None при ошибке/таймауте
        """
        for attempt in range(max_attempts):
            status = await self.get_task_status(task_id)

            if not status:
                await asyncio.sleep(delay)
                continue

            task_status = status.get("data", {}).get("status")

            if task_status == "COMPLETED":
                logger.info(f"Task {task_id} completed successfully")
                return status
            elif task_status == "FAILED":
                logger.error(f"Task {task_id} failed")
                return status

            logger.debug(
                f"Task {task_id} status: {task_status}, attempt {attempt + 1}/{max_attempts}"
            )
            await asyncio.sleep(delay)

        logger.warning(f"Task {task_id} timeout after {max_attempts} attempts")
        return None

    # =========================================================================
    # High-level convenience methods
    # =========================================================================

    async def text_to_video(
        self,
        prompt: str,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        quality: str = "std",
    ) -> Optional[Dict]:
        """
        Упрощённый метод для текст-в-видео (T2V)

        Args:
            prompt: Текстовый промпт
            duration: Длительность (3-15 сек)
            aspect_ratio: Формат видео
            quality: "pro" или "std"

        Returns:
            Dict с task_id
        """
        if quality == "pro":
            return await self.generate_video_pro(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
            )
        else:
            return await self.generate_video_std(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
            )

    async def image_to_video(
        self,
        image_url: str,
        prompt: str = "Animate this image naturally",
        duration: int = 5,
        aspect_ratio: str = "16:9",
        quality: str = "std",
    ) -> Optional[Dict]:
        """
        Упрощённый метод для изображение-в-видео (I2V)

        Args:
            image_url: URL изображения
            prompt: Текстовый промпт
            duration: Длительность
            aspect_ratio: Формат видео
            quality: "pro" или "std"

        Returns:
            Dict с task_id
        """
        if quality == "pro":
            return await self.generate_video_omni_pro(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
                start_image_url=image_url,
            )
        else:
            return await self.generate_video_omni_std(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
                start_image_url=image_url,
            )

    async def video_to_video(
        self,
        video_url: str,
        prompt: str,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        quality: str = "std",
    ) -> Optional[Dict]:
        """
        Упрощённый метод для видео-в-видео (R2V)

        Args:
            video_url: URL референсного видео
            prompt: Текстовый промпт (используйте @Video1 для ссылки на видео)
            duration: Длительность
            aspect_ratio: Формат видео
            quality: "pro" или "std"

        Returns:
            Dict с task_id
        """
        if quality == "pro":
            return await self.generate_video_omni_pro_r2v(
                prompt=prompt,
                video_url=video_url,
                duration=duration,
                aspect_ratio=aspect_ratio,
            )
        else:
            return await self.generate_video_omni_std_r2v(
                prompt=prompt,
                video_url=video_url,
                duration=duration,
                aspect_ratio=aspect_ratio,
            )

    # =========================================================================
    # Private HTTP Methods
    # =========================================================================

    async def _post_request(self, url: str, payload: Dict) -> Optional[Dict]:
        """Execute POST request to Kling API"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    url,
                    json=payload,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    data = await response.json()

                    if response.status == 200:
                        task_id = data.get("data", {}).get("task_id")
                        logger.info(
                            f"Kling task created successfully: {task_id}, payload_duration={payload.get('duration')}"
                        )
                        return {
                            "task_id": task_id,
                            "status": data.get("data", {}).get("status", "CREATED"),
                        }
                    else:
                        logger.error(
                            f"Kling API error {response.status}: {data}, URL: {url}"
                        )
                        return None

            except asyncio.TimeoutError:
                logger.error(f"Kling request timeout: {url}")
                return None
            except aiohttp.ClientError as e:
                logger.error(f"Kling request failed: {e}")
                return None
            except Exception as e:
                logger.exception(f"Unexpected error in Kling request: {e}")
                return None

    async def _get_request(
        self, url: str, params: Optional[Dict] = None
    ) -> Optional[Dict]:
        """Execute GET request to Kling API"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    url,
                    params=params,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status == 200:
                        # Проверяем Content-Type
                        content_type = response.headers.get("Content-Type", "")

                        if "application/json" in content_type:
                            return await response.json()
                        else:
                            # Получили HTML (ошибка сервера)
                            text = await response.text()
                            logger.error(
                                f"Kling API returned HTML instead of JSON: {text[:500]}"
                            )
                            return None
                    else:
                        # Пробуем получить JSON
                        try:
                            data = await response.json()
                            logger.error(f"Kling API error {response.status}: {data}")
                        except:
                            # HTML ошибка
                            text = await response.text()
                            logger.error(
                                f"Kling API error {response.status}, HTML: {text[:500]}"
                            )
                        return None

            except asyncio.TimeoutError:
                logger.error(f"Kling request timeout: {url}")
                return None
            except aiohttp.ClientError as e:
                logger.error(f"Kling request failed: {e}")
                return None
            except Exception as e:
                logger.exception(f"Unexpected error in Kling request: {e}")
                return None


# =============================================================================
# Module initialization
# =============================================================================

from bot.config import config

# Initialize service with API key (prefer FREEPIK_API_KEY, fallback to KLING_API_KEY)
kling_service = KlingService(
    api_key=config.FREEPIK_API_KEY or config.KLING_API_KEY,
    base_url=config.FREEPIK_BASE_URL,
)
