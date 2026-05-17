"""Generic PiAPI fallback provider for 2Loop generation models.

The project keeps primary providers (Kie.ai wrappers) for backwards compatibility,
but every content model should have a last-resort route through PiAPI.  PiAPI uses
one task endpoint and model-specific task_type/input payloads, so this service
normalizes image/video requests to the common `{task_id: ...}` shape used by the
handlers.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import aiohttp

from bot.config import config

logger = logging.getLogger(__name__)


class PiapiFallbackService:
    """Fallback client for PiAPI task API."""

    TASK_ENDPOINT = "/api/v1/task"

    IMAGE_MODEL_MAP: dict[str, tuple[str, str]] = {
        "banana_pro": ("gemini", "nano-banana-pro"),
        "nanobanana": ("gemini", "nano-banana-pro"),
        "nano_banana_pro": ("gemini", "nano-banana-pro"),
        "banana_2": ("gemini", "nano-banana-2"),
        "seedream": ("seedream", "generate"),
        "seedream_45": ("seedream", "generate"),
        "seedream_edit": ("seedream", "edit"),
        "seedream_5_lite": ("seedream", "generate"),
        "gpt_image_2": ("gpt-image", "image-to-image"),
        "flux_pro": ("Qubico/flux1-dev", "txt2img"),
        "z_image_turbo": ("Qubico/flux1-dev", "txt2img"),
    }

    VIDEO_MODEL_MAP: dict[str, tuple[str, str]] = {
        "v3_std": ("kling", "video_generation"),
        "v3_pro": ("kling", "video_generation"),
        "v3_omni_std": ("kling", "video_generation"),
        "v3_omni_pro": ("kling", "video_generation"),
        "v26_pro": ("kling", "video_generation"),
        "v26_motion_pro": ("kling", "motion_control"),
        "v26_motion_std": ("kling", "motion_control"),
        "runway": ("runway", "generate"),
        "grok_imagine": ("grok", "image_to_video"),
        "aleph": ("aleph", "video_to_video"),
        "glow": ("glow", "video_to_video"),
        "seedance2": ("seedance", "image_to_video"),
        "wan_27": ("wan", "image_to_video"),
    }

    def __init__(self, api_key: str = "", base_url: str = ""):
        self.api_key = api_key or config.PIAPI_API_KEY
        self.base_url = (base_url or config.PIAPI_BASE_URL or "https://api.piapi.ai").rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    @property
    def headers(self) -> Optional[Dict[str, str]]:
        if not self.api_key:
            return None
        return {
            "x-api-key": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
        return self._session

    @staticmethod
    def _extract_task_id(data: Dict[str, Any]) -> Optional[str]:
        candidates = [
            data.get("task_id"),
            data.get("taskId"),
            data.get("id"),
            (data.get("data") or {}).get("task_id") if isinstance(data.get("data"), dict) else None,
            (data.get("data") or {}).get("taskId") if isinstance(data.get("data"), dict) else None,
            (data.get("data") or {}).get("id") if isinstance(data.get("data"), dict) else None,
        ]
        return next((str(item) for item in candidates if item), None)

    async def create_task(
        self,
        model: str,
        task_type: str,
        input_data: Dict[str, Any],
        task_config: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        headers = self.headers
        if not headers:
            logger.error("PIAPI_API_KEY is not configured; fallback unavailable")
            return None

        payload: Dict[str, Any] = {
            "model": model,
            "task_type": task_type,
            "input": input_data,
        }
        if task_config:
            payload["config"] = task_config

        session = await self._get_session()
        try:
            async with session.post(
                f"{self.base_url}{self.TASK_ENDPOINT}", headers=headers, json=payload
            ) as response:
                text = await response.text()
                try:
                    data = json.loads(text) if text else {}
                except json.JSONDecodeError:
                    logger.error("PiAPI fallback returned non-JSON: %s", text[:500])
                    return None
                if response.status >= 400:
                    logger.error("PiAPI fallback HTTP %s: %s", response.status, text[:500])
                    return None
                task_id = self._extract_task_id(data)
                if not task_id:
                    logger.error("PiAPI fallback response has no task id: %s", data)
                    return None
                return {"task_id": task_id, "provider": "piapi", "raw": data}
        except Exception as exc:  # pragma: no cover - network defensive path
            logger.exception("PiAPI fallback request failed: %s", exc)
            return None

    async def generate_image(
        self,
        provider_model: str,
        prompt: str,
        aspect_ratio: str = "1:1",
        image_urls: Optional[List[str]] = None,
        callback_url: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        model, task_type = self.IMAGE_MODEL_MAP.get(
            provider_model, self.IMAGE_MODEL_MAP["banana_pro"]
        )
        input_data: Dict[str, Any] = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "image_input": image_urls or [],
            "image_urls": image_urls or [],
        }
        task_config = {"webhook_config": {"endpoint": callback_url, "secret": ""}} if callback_url else None
        return await self.create_task(model, task_type, input_data, task_config)

    async def generate_video(
        self,
        provider_model: str,
        prompt: str,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        image_url: Optional[str] = None,
        video_url: Optional[str] = None,
        image_urls: Optional[List[str]] = None,
        video_urls: Optional[List[str]] = None,
        callback_url: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        model, task_type = self.VIDEO_MODEL_MAP.get(
            provider_model, self.VIDEO_MODEL_MAP["v3_std"]
        )
        input_data: Dict[str, Any] = {
            "prompt": prompt,
            "model_name": provider_model,
            "duration": int(duration),
            "aspect_ratio": aspect_ratio,
            "image_url": image_url,
            "video_url": video_url or (video_urls[0] if video_urls else None),
            "image_urls": image_urls or ([] if not image_url else [image_url]),
            "video_urls": video_urls or ([] if not video_url else [video_url]),
            "prefer_http": True,
        }
        input_data = {k: v for k, v in input_data.items() if v not in (None, [], "")}
        task_config = {"webhook_config": {"endpoint": callback_url, "secret": ""}} if callback_url else None
        return await self.create_task(model, task_type, input_data, task_config)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


piapi_fallback_service = PiapiFallbackService()
