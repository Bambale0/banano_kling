"""
Kling API Service - PiAPI Kling 3.0 (Freepik completely removed)

Endpoints:
- POST /api/v1/task - Create task
- GET /api/v1/task - List tasks
- GET /api/v1/task/{task_id} - Get task status

Docs: kling_api.md
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


class KlingService:
    """Сервис для работы с PiAPI Kling 3.0 API"""

    ENDPOINTS = {
        "task": "/api/v1/task",
    }

    ASPECT_RATIOS = ["16:9", "9:16", "1:1"]
    DURATIONS = list(range(3, 16))

    def __init__(
        self, api_key: Optional[str] = None, base_url: str = "https://api.piapi.ai"
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.headers = (
            {
                "x-api-key": api_key,
                "Content-Type": "application/json",
            }
            if api_key
            else None
        )

    async def _post(self, url: str, payload: Dict) -> Optional[Dict]:
        if not self.headers:
            logger.error("API key not configured")
            return None
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    url,
                    json=payload,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        task_id = data.get("data", {}).get("task_id")
                        logger.info(f"Task created: {task_id}")
                        return {
                            "task_id": task_id,
                            "status": data.get("data", {}).get("status", "pending"),
                        }
                    else:
                        data = await resp.json()
                        logger.error(f"API error {resp.status}: {data}")

                        # Handle specific error codes
                        if resp.status == 429:
                            return {
                                "error": "rate_limit",
                                "message": "Достигнут дневной лимит использования Kling API. Попробуйте завтра или выберите другую модель.",
                                "status_code": 429,
                            }
                        elif resp.status == 402:
                            return {
                                "error": "insufficient_credits",
                                "message": "Недостаточно кредитов на аккаунте Kling API.",
                                "status_code": 402,
                            }
                        else:
                            return {
                                "error": "api_error",
                                "message": f"Ошибка API Kling: {data.get('message', 'Неизвестная ошибка')}",
                                "status_code": resp.status,
                            }
            except Exception as e:
                logger.exception(f"Request error: {e}")
                return {
                    "error": "network_error",
                    "message": f"Ошибка сети: {str(e)}",
                    "status_code": 0,
                }

    async def _get(self, url: str, params: Optional[Dict] = None) -> Optional[Dict]:
        if not self.headers:
            logger.error("API key not configured")
            return None
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    url,
                    params=params,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.error(f"API error {resp.status}")
                        return None
            except Exception as e:
                logger.exception(f"Request error: {e}")
                return None

    async def create_task(
        self, task_type: str, input_data: Dict, config: Optional[Dict] = None
    ) -> Optional[Dict]:
        url = f"{self.base_url}{self.ENDPOINTS['task']}"
        payload = {
            "model": "kling",
            "task_type": task_type,
            "input": input_data,
        }
        if config:
            payload["config"] = config
        return await self._post(url, payload)

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        url = f"{self.base_url}{self.ENDPOINTS['task']}/{task_id}"
        return await self._get(url)

    async def list_tasks(self, page: int = 1, page_size: int = 20) -> Optional[Dict]:
        url = f"{self.base_url}{self.ENDPOINTS['task']}"
        params = {"page": page, "page_size": page_size}
        return await self._get(url, params)

    async def generate_video_generation(
        self,
        prompt: str,
        mode: str = "std",
        duration: int = 5,
        aspect_ratio: str = "16:9",
        image_url: Optional[str] = None,
        image_tail_url: Optional[str] = None,
        enable_audio: bool = False,
        prefer_multi_shots: bool = False,
        multi_shots: Optional[List[Dict[str, Any]]] = None,
        images: Optional[List[str]] = None,
        webhook_url: Optional[str] = None,
        service_mode: str = "public",
    ) -> Optional[Dict]:
        duration = max(3, min(duration, 15))
        input_data = {
            "prompt": prompt,
            "version": "3.0",
            "mode": mode,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "enable_audio": enable_audio,
            "prefer_multi_shots": prefer_multi_shots,
        }
        if image_url:
            input_data["image_url"] = image_url
        if image_tail_url:
            input_data["image_tail_url"] = image_tail_url
        if multi_shots:
            input_data["multi_shots"] = [
                {"prompt": s["prompt"], "duration": max(1, min(s["duration"], 14))}
                for s in multi_shots[:6]
            ]
        config = {"service_mode": service_mode}
        if webhook_url:
            config["webhook_config"] = {"endpoint": webhook_url, "secret": ""}
        return await self.create_task("video_generation", input_data, config)

    async def generate_motion_control(
        self,
        image_url: str,
        video_url: Optional[str] = None,
        preset_motion: Optional[str] = None,
        prompt: Optional[str] = None,
        motion_direction: str = "video",
        keep_original_sound: bool = True,
        mode: str = "std",
        aspect_ratio: str = "16:9",
        webhook_url: Optional[str] = None,
        service_mode: str = "public",
    ) -> Optional[Dict]:
        input_data = {
            "image_url": image_url,
            "mode": mode,
            "motion_direction": motion_direction,
            "keep_original_sound": keep_original_sound,
        }
        if video_url:
            input_data["video_url"] = video_url
        if preset_motion:
            input_data["preset_motion"] = preset_motion
        if prompt:
            input_data["prompt"] = prompt
        config = {"service_mode": service_mode}
        if webhook_url:
            config["webhook_config"] = {"endpoint": webhook_url, "secret": ""}
        return await self.create_task("motion_control", input_data, config)

    async def generate_omni_video_generation(
        self,
        prompt: str,
        version: str = "3.0",
        resolution: str = "720p",
        duration: int = 5,
        aspect_ratio: str = "16:9",
        enable_audio: bool = False,
        multi_shots: Optional[List[Dict[str, Any]]] = None,
        images: Optional[List[str]] = None,
        webhook_url: Optional[str] = None,
        service_mode: str = "public",
    ) -> Optional[Dict]:
        input_data = {
            "prompt": prompt,
            "version": version,
            "resolution": resolution,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "enable_audio": enable_audio,
        }
        if multi_shots:
            input_data["multi_shots"] = multi_shots
        if images:
            input_data["images"] = images
        config = {"service_mode": service_mode}
        if webhook_url:
            config["webhook_config"] = {"endpoint": webhook_url, "secret": ""}
        return await self.create_task("omni_video_generation", input_data, config)

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
        # Collect reference images
        images = None
        if image_url:
            images = [image_url]
        if elements:
            elem_images = []
            for el in elements:
                elem_images.extend(el.get("reference_image_urls", []))
                frontal = el.get("frontal_image_url")
                if frontal:
                    elem_images.append(frontal)
            if images is None:
                images = elem_images
            else:
                images.extend(elem_images)
        # Deduplicate images
        if images:
            seen = set()
            images = [img for img in images if img not in seen and not seen.add(img)]
        # Enhance prompt for consistency if images provided
        if images:
            if "omni" in model.lower():
                # For Kling 3.0 Omni, use @image_1 reference as per API docs
                prompt = f"Use @image_1 as first frame. {prompt}"
            else:
                # For Kling 3.0 std/pro, explicitly reference the image in prompt for better control
                prompt = f"Use the provided reference image as the starting point and main subject. {prompt}"
        # Map legacy models to PiAPI task_types/mode
        if model in ["v3_std", "v3_pro"]:
            # Use Omni API for Pro models and when images are provided for better prompt following
            if "pro" in model or images:
                # Determine resolution based on model quality
                resolution = "1080p" if "pro" in model.lower() else "720p"
                return await self.generate_omni_video_generation(
                    prompt=prompt,
                    duration=duration,
                    aspect_ratio=aspect_ratio,
                    enable_audio=generate_audio,
                    images=images,
                    webhook_url=webhook_url,
                    resolution=resolution,
                )
            else:
                # Use standard API for Std model without images
                mode = "std"
                return await self.generate_video_generation(
                    prompt=prompt,
                    mode=mode,
                    duration=duration,
                    aspect_ratio=aspect_ratio,
                    image_url=image_url,
                    image_tail_url=end_image_url,
                    enable_audio=generate_audio,
                    webhook_url=webhook_url,
                )
        elif "motion" in model.lower():
            return await self.generate_motion_control(
                image_url=image_url,
                video_url=video_url,
                prompt=prompt if negative_prompt is None else prompt,
                aspect_ratio=aspect_ratio,
                webhook_url=webhook_url,
            )
        elif "omni" in model.lower():
            # Determine resolution based on model quality
            resolution = "1080p" if "pro" in model.lower() else "720p"
            return await self.generate_omni_video_generation(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
                enable_audio=generate_audio,
                images=images,
                webhook_url=webhook_url,
                resolution=resolution,
            )
        else:
            logger.error(f"Unknown model: {model}. Defaulting to video_generation std.")
            return await self.generate_video_generation(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
                webhook_url=webhook_url,
            )

    async def wait_for_completion(
        self, task_id: str, max_attempts: int = 60, delay: int = 5
    ) -> Optional[Dict]:
        for attempt in range(max_attempts):
            status = await self.get_task_status(task_id)
            if not status:
                await asyncio.sleep(delay)
                continue
            task_status = status.get("data", {}).get("status", "").lower()
            if task_status in ["completed", "succeeded"]:
                logger.info(f"Task {task_id} completed")
                return status
            elif task_status in ["failed", "error"]:
                logger.error(f"Task {task_id} failed")
                return status
            logger.debug(f"Task {task_id}: {task_status}, attempt {attempt+1}")
            await asyncio.sleep(delay)
        logger.warning(f"Task {task_id} timeout")
        return None


from bot.config import config

kling_service = KlingService(
    api_key=config.PIAPI_API_KEY,
    base_url=config.PIAPI_BASE_URL or "https://api.piapi.ai",
)
