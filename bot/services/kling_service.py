import asyncio
import logging
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


class KlingService:
    """Сервис для работы с Kling 3 API через Freepik"""

    ENDPOINTS = {
        "v3_pro": "/v1/ai/video/kling-v3-pro",
        "v3_std": "/v1/ai/video/kling-v3-std",
        "v3_omni_pro": "/v1/ai/video/kling-v3-omni-pro",
        "v3_omni_std": "/v1/ai/video/kling-v3-omni-std",
        "v3_omni_pro_r2v": "/v1/ai/reference-to-video/kling-v3-omni-pro",
        "v3_omni_std_r2v": "/v1/ai/reference-to-video/kling-v3-omni-std",
    }

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.headers = {"x-freepik-api-key": api_key}

    async def generate_video(
        self,
        prompt: str,
        model: str = "v3_std",
        duration: int = 5,
        aspect_ratio: str = "16:9",
        webhook_url: Optional[str] = None,
        image_url: Optional[str] = None,  # Для image-to-video
        end_image_url: Optional[str] = None,
        elements: Optional[List[Dict]] = None,
        negative_prompt: Optional[str] = None,
        cfg_scale: float = 0.5,
    ) -> Optional[Dict]:
        """
        Создание задачи генерации видео

        Returns:
            Dict с task_id или None при ошибке
        """
        endpoint = self.ENDPOINTS.get(model, self.ENDPOINTS["v3_std"])
        url = f"{self.base_url}{endpoint}"

        payload = {
            "prompt": prompt,
            "duration": str(duration),
            "aspect_ratio": aspect_ratio,
            "cfg_scale": cfg_scale,
        }

        if webhook_url:
            payload["webhook_url"] = webhook_url

        # Для image-to-video
        if image_url:
            payload["image_url"] = image_url
        if end_image_url:
            payload["end_image_url"] = end_image_url

        # Для multi-shot или элементов
        if elements:
            payload["elements"] = elements

        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        logger.info(f"Kling request: {model}, prompt: {prompt[:50]}...")

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
                        logger.info(f"Kling task created: {data.get('task_id')}")
                        return {
                            "task_id": data.get("task_id"),
                            "status": data.get("status", "CREATED"),
                        }
                    else:
                        logger.error(f"Kling error: {data}")
                        return None

            except Exception as e:
                logger.exception(f"Kling request failed: {e}")
                return None

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        """Проверка статуса задачи"""
        url = f"{self.base_url}/v1/ai/video/kling-v3/{task_id}"

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    return None
            except Exception as e:
                logger.exception(f"Get task status failed: {e}")
                return None

    async def wait_for_completion(
        self, task_id: str, max_attempts: int = 60, delay: int = 5
    ) -> Optional[Dict]:
        """
        Опрос статуса до завершения (для синхронного режима)
        """
        for attempt in range(max_attempts):
            status = await self.get_task_status(task_id)

            if not status:
                await asyncio.sleep(delay)
                continue

            task_status = status.get("data", {}).get("status")

            if task_status == "COMPLETED":
                return status
            elif task_status == "FAILED":
                logger.error(f"Task {task_id} failed")
                return None

            logger.debug(f"Task {task_id} status: {task_status}, attempt {attempt}")
            await asyncio.sleep(delay)

        logger.warning(f"Task {task_id} timeout")
        return None

    async def text_to_video(
        self,
        prompt: str,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        quality: str = "std",
    ) -> Optional[Dict]:
        """
        Упрощённый метод для текст-в-видео
        """
        model = f"v3_{quality}"
        return await self.generate_video(
            prompt=prompt, model=model, duration=duration, aspect_ratio=aspect_ratio
        )

    async def image_to_video(
        self, image_url: str, prompt: str = "", duration: int = 5, quality: str = "std"
    ) -> Optional[Dict]:
        """
        Упрощённый метод для изображение-в-видео
        """
        model = f"v3_omni_{quality}_r2v"
        return await self.generate_video(
            prompt=prompt or "Animate this image naturally",
            model=model,
            duration=duration,
            image_url=image_url,
        )


# Инициализация
from bot.config import config

# Приоритет: FREEPIK_API_KEY → KLING_API_KEY
kling_service = KlingService(
    api_key=config.FREEPIK_API_KEY or config.KLING_API_KEY,
    base_url=config.FREEPIK_BASE_URL,
)
