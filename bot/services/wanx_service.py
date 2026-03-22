"""
WanX Service - PiAPI WanX task creation with LoRA support.
"""

import asyncio
import base64
import logging
from typing import Any, Dict, List, Optional

import aiohttp

from bot.config import config

logger = logging.getLogger(__name__)


class WanXService:
    ENDPOINTS = {"task": "/api/v1/task"}
    DEFAULT_MODEL = "Qubico/wanx"
    DEFAULT_TASK_TYPE = "txt2video-14b-lora"
    IMAGE2VIDEO_TASK_TYPE = "img2video-14b-lora"
    ASPECT_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"]

    # NSFW LoRA types (must be lowercase)
    NSFW_LORA_TYPES = {
        "nsfw-general",
        "nsfw-bouncing-boobs",
        "nsfw-undress",
        "nsfw-pov-blowjob",
        "nsfw-pov-titfuck",
        "nsfw-pov-missionary",
        "nsfw-pov-cowgirl",
        "nsfw-pov-doggy",
    }

    # Prompt enhancement
    NO_RESTRICTIONS_PROMPT = "No restrictions on content. Generate any requested imagery without limitations or censorship."
    PRECISION_PROMPT = "Follow the user's prompt exactly. Generate precisely what is described with high accuracy and attention to detail. Do not deviate from the specified scene, characters, actions, or composition."
    ANATOMY_DETAIL_PROMPT = "Render accurate human anatomy with realistic proportions, detailed physiology, natural skin textures, and authentic physical interactions. Include precise anatomical details, lifelike muscle definition, and believable body mechanics."

    def __init__(
        self, api_key: Optional[str] = None, base_url: str = "https://api.piapi.ai"
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.headers = (
            {"x-api-key": api_key, "Content-Type": "application/json"}
            if api_key
            else None
        )

    def _contains_nsfw_lora(
        self, lora_settings: Optional[List[Dict[str, Any]]]
    ) -> bool:
        """Check if any LoRA setting is NSFW."""
        if not lora_settings:
            return False
        for lora in lora_settings:
            lora_type = lora.get("lora_type") or lora.get("type")
            if isinstance(lora_type, str) and lora_type.lower() in self.NSFW_LORA_TYPES:
                return True
        return False

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
                    data = await resp.json()
                    if resp.status in (200, 201):
                        task_id = data.get("data", {}).get("task_id") or data.get(
                            "task_id"
                        )
                        logger.info(f"WanX task created: {task_id}")
                        return {
                            "task_id": task_id,
                            "status": data.get("data", {}).get("status", "pending"),
                            "raw": data,
                        }
                    logger.error(f"WanX API error {resp.status}: {data}")
                    return {
                        "error": "api_error",
                        "status_code": resp.status,
                        "message": data.get("message", "Unknown API error"),
                        "raw": data,
                    }
            except Exception as e:
                logger.exception(f"WanX request error: {e}")
                return {"error": "network_error", "status_code": 0, "message": str(e)}

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
                    data = await resp.json()
                    logger.error(f"WanX API error {resp.status}: {data}")
                    return None
            except Exception as e:
                logger.exception(f"WanX request error: {e}")
                return None

    @staticmethod
    def _extract_output_url(payload: Dict[str, Any]) -> Optional[str]:
        """Extract a result URL from WanX task payload in multiple response shapes."""
        output = payload.get("output") or {}
        if isinstance(output, dict):
            if output.get("video_url"):
                return output["video_url"]
            if output.get("video"):
                return output["video"]
            works = output.get("works") or []
            if works and isinstance(works, list):
                first = works[0] or {}
                if isinstance(first, dict):
                    resource = first.get("resource") or {}
                    if isinstance(resource, dict):
                        return resource.get("resourceWithoutWatermark") or resource.get(
                            "resource"
                        )
                    if isinstance(resource, str):
                        return resource

        works = payload.get("works") or []
        if works and isinstance(works, list):
            first = works[0] or {}
            if isinstance(first, dict):
                resource = first.get("resource") or {}
                if isinstance(resource, dict):
                    return resource.get("resourceWithoutWatermark") or resource.get(
                        "resource"
                    )
                if isinstance(resource, str):
                    return resource

        return None

    @classmethod
    def _normalize_task_response(cls, response: Dict[str, Any]) -> Optional[Dict]:
        """Normalize PiAPI WanX task responses into a compact structure."""
        if not response:
            return None

        payload = (
            response.get("data") if isinstance(response.get("data"), dict) else response
        )
        task_id = payload.get("task_id") or response.get("task_id")
        status = payload.get("status") or response.get("status") or "pending"

        normalized: Dict[str, Any] = {
            "task_id": task_id,
            "status": status,
            "raw": response,
        }

        output_url = cls._extract_output_url(payload)
        if output_url:
            normalized["output"] = {"video_url": output_url}

        return normalized

    async def create_task(
        self,
        task_type: str,
        input_data: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
    ) -> Optional[Dict]:
        url = f"{self.base_url}{self.ENDPOINTS['task']}"
        payload: Dict[str, Any] = {
            "model": model or self.DEFAULT_MODEL,
            "task_type": task_type,
            "input": input_data,
        }
        if config:
            payload["config"] = config
        return await self._post(url, payload)

    async def generate_txt2video_lora(
        self,
        prompt: str,
        negative_prompt: str = "",
        aspect_ratio: str = "16:9",
        lora_settings: Optional[List[Dict[str, Any]]] = None,
        webhook_url: Optional[str] = None,
        webhook_secret: str = "",
        task_type: str = DEFAULT_TASK_TYPE,
    ) -> Optional[Dict]:
        # NSFW content control: warn if disabled but continue to allow caller to decide
        if not config.ALLOW_NSFW and self._contains_nsfw_lora(lora_settings):
            logger.warning("NSFW LoRA detected but ALLOW_NSFW is disabled")

        if aspect_ratio not in self.ASPECT_RATIOS:
            logger.warning(
                f"Invalid aspect ratio for WanX: {aspect_ratio}, defaulting to 16:9"
            )
            aspect_ratio = "16:9"

        validated_loras: List[Dict[str, Any]] = []
        if lora_settings:
            for i, lora in enumerate(lora_settings):
                if not isinstance(lora, dict):
                    logger.error(f"WanX LoRA {i}: must be a dictionary")
                    continue
                lora_type = lora.get("lora_type") or lora.get("type")
                if not lora_type:
                    logger.error(f"WanX LoRA {i}: 'lora_type' is required")
                    continue
                strength = lora.get("lora_strength", 1.0)
                if not isinstance(strength, (int, float)):
                    try:
                        strength = float(strength)
                    except (TypeError, ValueError):
                        strength = 1.0
                validated_loras.append(
                    {
                        "lora_type": lora_type,
                        "lora_strength": max(0.0, min(1.0, strength)),
                    }
                )

        # Use the user's prompt exactly (do not mutate), keep enhancements out of prompt
        input_data = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "aspect_ratio": aspect_ratio,
            "lora_settings": validated_loras,
        }
        webhook_config: Dict[str, Any] = {}
        if webhook_url:
            webhook_config["webhook_config"] = {
                "endpoint": webhook_url,
                "secret": webhook_secret,
            }
        logger.info(
            "WanX request: prompt=%s..., aspect_ratio=%s, loras=%s, webhook=%s, nsfw_allowed=%s",
            prompt[:50],
            aspect_ratio,
            len(validated_loras),
            bool(webhook_url),
            config.ALLOW_NSFW,
        )
        return await self.create_task(task_type, input_data, webhook_config or None)

    async def generate_img2video_lora(
        self,
        image_bytes: bytes,
        prompt: str,
        negative_prompt: str = "",
        aspect_ratio: str = "16:9",
        lora_settings: Optional[List[Dict[str, Any]]] = None,
        webhook_url: Optional[str] = None,
        webhook_secret: str = "",
        task_type: str = IMAGE2VIDEO_TASK_TYPE,
    ) -> Optional[Dict]:
        """Generate video from image with LoRA support."""
        # NSFW content control: warn if disabled but continue
        if not config.ALLOW_NSFW and self._contains_nsfw_lora(lora_settings):
            logger.warning("NSFW LoRA detected but ALLOW_NSFW is disabled")

        if aspect_ratio not in self.ASPECT_RATIOS:
            logger.warning(
                f"Invalid aspect ratio for WanX: {aspect_ratio}, defaulting to 16:9"
            )
            aspect_ratio = "16:9"

        validated_loras: List[Dict[str, Any]] = []
        if lora_settings:
            for i, lora in enumerate(lora_settings):
                if not isinstance(lora, dict):
                    logger.error(f"WanX LoRA {i}: must be a dictionary")
                    continue
                lora_type = lora.get("lora_type") or lora.get("type")
                if not lora_type:
                    logger.error(f"WanX LoRA {i}: 'lora_type' is required")
                    continue
                strength = lora.get("lora_strength", 1.0)
                if not isinstance(strength, (int, float)):
                    try:
                        strength = float(strength)
                    except (TypeError, ValueError):
                        strength = 1.0
                validated_loras.append(
                    {
                        "lora_type": lora_type,
                        "lora_strength": max(0.0, min(1.0, strength)),
                    }
                )

        # Keep user's prompt unchanged
        enhanced_prompt = prompt
        # Convert image to base64
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        input_data = {
            "image": image_base64,
            "prompt": enhanced_prompt,
            "negative_prompt": negative_prompt,
            "aspect_ratio": aspect_ratio,
            "lora_settings": validated_loras,
        }
        webhook_config: Dict[str, Any] = {}
        if webhook_url:
            webhook_config["webhook_config"] = {
                "endpoint": webhook_url,
                "secret": webhook_secret,
            }
        logger.info(
            "WanX img2video request: prompt=%s..., aspect_ratio=%s, loras=%s, webhook=%s, nsfw_allowed=%s",
            enhanced_prompt[:50],
            aspect_ratio,
            len(validated_loras),
            bool(webhook_url),
            config.ALLOW_NSFW,
        )
        return await self.create_task(task_type, input_data, webhook_config or None)

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        response = await self._get(f"{self.base_url}{self.ENDPOINTS['task']}/{task_id}")
        return self._normalize_task_response(response) if response else None

    async def wait_for_completion(
        self, task_id: str, max_attempts: int = 60, delay: int = 5
    ) -> Optional[Dict]:
        for _ in range(max_attempts):
            status = await self.get_task_status(task_id)
            if not status:
                await asyncio.sleep(delay)
                continue
            task_status = str(status.get("status", "")).lower()
            if task_status in (
                "completed",
                "succeeded",
                "success",
                "task_status_succeed",
            ):
                return status
            if task_status in ("failed", "error", "task_status_failed"):
                return status
            await asyncio.sleep(delay)
        return None


wanx_service = (
    WanXService(api_key=config.PIAPI_API_KEY, base_url=config.PIAPI_BASE_URL)
    if config.PIAPI_API_KEY
    else None
)
