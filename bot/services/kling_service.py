"""
Kling 3 API Service - Реализация всех методов Freepik API для Kling 3

Документация: https://docs.freepik.com/apis/freepik/ai/kling-v3

Endpoints:
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
    """Сервис для работы с Kling 3 API через Freepik"""

    # API Endpoints (without /v1 prefix - it's already in base_url)
    ENDPOINTS = {
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
    DURATIONS = ["3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15"]

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "x-freepik-api-key": api_key,
            "Content-Type": "application/json"
        }

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

        logger.info(f"Kling 3 Pro request: prompt={prompt[:50]}..., duration={duration}, aspect={aspect_ratio}")

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

        logger.info(f"Kling 3 Std request: prompt={prompt[:50]}..., duration={duration}, aspect={aspect_ratio}")

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
        
        payload = {
            "prompt": prompt,
            "duration": duration_str,
            "aspect_ratio": aspect_ratio if aspect_ratio in self.ASPECT_RATIOS else "16:9",
            "cfg_scale": min(max(cfg_scale, 0), 2),  # max 2 по документации
            "generate_audio": generate_audio,
        }

        if multi_shot:
            payload["multi_shot"] = True
            payload["shot_type"] = shot_type

        if webhook_url:
            payload["webhook_url"] = webhook_url
        
        # ПРАВИЛЬНО по документации: start_image_url и end_image_url напрямую
        if start_image_url:
            payload["start_image_url"] = start_image_url
        
        if end_image_url:
            payload["end_image_url"] = end_image_url
        
        # ПРАВИЛЬНО: element_list, не elements
        if elements:
            element_list = []
            for elem in elements:
                if isinstance(elem, dict):
                    # Проверяем правильный формат
                    if "reference_image_urls" in elem or "frontal_image_url" in elem:
                        element_list.append(elem)
                    else:
                        # Конвертация из старого формата
                        element_list.append({
                            "reference_image_urls": elem.get("reference_image_urls", []),
                            "frontal_image_url": elem.get("frontal_image_url", elem.get("image_url"))
                        })
            if element_list:
                payload["element_list"] = element_list
        
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        
        if voice_ids:
            payload["voice_ids"] = voice_ids[:2]  # Max 2
        
        # ПРАВИЛЬНО: multi_prompt без index, duration как строка
        if multi_prompt:
            formatted_multi_prompt = []
            for item in multi_prompt:
                if isinstance(item, dict):
                    formatted_multi_prompt.append({
                        "prompt": item.get("prompt", ""),
                        "duration": str(item.get("duration", 5))  # Строка!
                    })
                else:
                    formatted_multi_prompt.append(item)
            payload["multi_prompt"] = formatted_multi_prompt

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

        logger.info(f"Kling 3 Omni Pro request: prompt={prompt[:50]}...")

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
            "aspect_ratio": aspect_ratio if aspect_ratio in valid_aspect_ratios else "16:9",
            "generate_audio": generate_audio,
            "shot_type": "customize",
        }

        if webhook_url:
            payload["webhook_url"] = webhook_url
        
        # Используем image_list как в документации
        if start_image_url or end_image_url:
            image_list = []
            if start_image_url:
                image_list.append({
                    "image_url": start_image_url,
                    "type": "first_frame"
                })
            if end_image_url:
                image_list.append({
                    "image_url": end_image_url,
                    "type": "end_frame"
                })
            payload["image_list"] = image_list
        
        if image_url:
            payload["image_url"] = image_url
        
        if image_urls:
            payload["image_urls"] = image_urls[:4]  # Max 4 images
        
        if elements:
            payload["elements"] = elements
        
        if voice_ids:
            payload["voice_ids"] = voice_ids[:2]  # Max 2 voices
        
        if multi_prompt:
            payload["multi_prompt"] = multi_prompt[:6]  # Max 6 shots

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
        end_image_url: Optional[str] = None,
        elements: Optional[List[Dict]] = None,
        negative_prompt: Optional[str] = None,
        cfg_scale: float = 0.5,
    ) -> Optional[Dict]:
        """
        Универсальный метод для создания видео (обратная совместимость)
        
        Args:
            prompt: Текстовый промпт
            model: Модель - "v3_pro", "v3_std", "v3_omni_pro", "v3_omni_std", "v3_omni_pro_r2v", "v3_omni_std_r2v"
            duration: Длительность (3-15 сек)
            aspect_ratio: Формат - "16:9", "9:16", "1:1"
            webhook_url: URL для вебхука
            image_url: URL изображения для I2V
            end_image_url: URL конечного кадра
            elements: Список элементов
            negative_prompt: Негативный промпт
            cfg_scale: Шкала CFG (0-2)
        
        Returns:
            Dict с task_id или None
        """
        # Map old model names to new methods
        model_map = {
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
        
        # Determine if it's R2V mode
        if model in ["v3_omni_pro_r2v", "v3_omni_std_r2v"]:
            if not image_url:
                logger.error("R2V mode requires image_url parameter")
                return None
            return await method(
                prompt=prompt,
                video_url=image_url,
                duration=duration,
                aspect_ratio=aspect_ratio,
                webhook_url=webhook_url,
                cfg_scale=cfg_scale,
            )
        else:
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

            logger.debug(f"Task {task_id} status: {task_status}, attempt {attempt + 1}/{max_attempts}")
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
                        logger.info(f"Kling task created successfully: {task_id}")
                        return {
                            "task_id": task_id,
                            "status": data.get("data", {}).get("status", "CREATED"),
                        }
                    else:
                        logger.error(f"Kling API error {response.status}: {data}, URL: {url}")
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

    async def _get_request(self, url: str, params: Optional[Dict] = None) -> Optional[Dict]:
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
                            logger.error(f"Kling API returned HTML instead of JSON: {text[:500]}")
                            return None
                    else:
                        # Пробуем получить JSON
                        try:
                            data = await response.json()
                            logger.error(f"Kling API error {response.status}: {data}")
                        except:
                            # HTML ошибка
                            text = await response.text()
                            logger.error(f"Kling API error {response.status}, HTML: {text[:500]}")
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
