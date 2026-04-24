"""
Kling API Service - Kie.ai only

Supported models/routes:
- Kling 3.0 video
- Kling 2.5 Turbo Pro text-to-video / image-to-video
- Kling AI Avatar Standard / Pro
- Kling 2.6 Motion Control
- Kling Glow preset flow

Endpoints:
- POST /api/v1/jobs/createTask
- GET  /api/v1/jobs/{task_id}

Important:
- This service must not silently accept non-Kling models.
- Grok, GPT Image, Nano Banana, Seedream and other providers must be routed
  through their own services from the generation handler.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


class KlingService:
    """Service for Kie.ai Kling-related task APIs."""

    KIE_BASE_URL = "https://api.kie.ai"
    CREATE_TASK_ENDPOINT = "/api/v1/jobs/createTask"

    ASPECT_RATIOS = {"16:9", "9:16", "1:1"}
    KLING_25_DURATIONS = {5, 10}
    KLING_25_CFG_MIN = 0.0
    KLING_25_CFG_MAX = 1.0

    KLING_3_MODELS = {"v3_std", "v3_pro", "kling_v3", "kling_3", "kling_3_pro"}
    KLING_25_MODELS = {"v26_pro", "kling_25_turbo_pro"}
    AVATAR_MODELS = {"avatar_std", "avatar_pro"}
    MOTION_MODELS = {"kling-2.6/motion-control", "motion_control"}
    GLOW_MODELS = {"glow"}

    NON_KLING_MODELS = {
        "grok_imagine",
        "grok_imagine_i2i",
        "banana_pro",
        "banana_2",
        "seedream_edit",
        "flux_pro",
        "gpt_image_2",
        "nano_banana_pro",
        "nano_banana_2",
    }

    def __init__(self, kie_key: Optional[str] = None):
        self.kie_key = kie_key or os.getenv("KIE_AI_API_KEY")
        self.kie_headers = (
            {
                "Authorization": f"Bearer {self.kie_key}",
                "Content-Type": "application/json",
            }
            if self.kie_key
            else None
        )

    # ------------------------------------------------------------------
    # Generic Kie.ai HTTP helpers
    # ------------------------------------------------------------------

    async def _kie_post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST to Kie.ai and normalize task creation response."""
        if not self.kie_headers:
            logger.error("Kie.ai API key not configured")
            return {
                "error": "missing_api_key",
                "message": "Kie.ai API key is not configured",
                "status_code": 0,
            }

        url = f"{self.KIE_BASE_URL}{endpoint}"

        async with aiohttp.ClientSession(trust_env=False) as session:
            try:
                async with session.post(
                    url,
                    json=payload,
                    headers=self.kie_headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    text = await resp.text()
                    return self._parse_kie_create_response(text)
            except Exception as exc:
                logger.exception("Kie.ai request error: %s", exc)
                return {
                    "error": "network_error",
                    "message": f"Network error: {exc}",
                    "status_code": 0,
                }

    async def _kie_get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """GET from Kie.ai."""
        if not self.kie_headers:
            logger.error("Kie.ai API key not configured")
            return None

        url = f"{self.KIE_BASE_URL}{endpoint}"
        headers = {k: v for k, v in self.kie_headers.items() if k != "Content-Type"}

        async with aiohttp.ClientSession(trust_env=False) as session:
            try:
                async with session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    text = await resp.text()
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError:
                        logger.error("Kie.ai invalid JSON response: %s", text[:500])
                        return None

                    if resp.status >= 400:
                        logger.error(
                            "Kie.ai GET error http_status=%s response=%s",
                            resp.status,
                            data,
                        )
                        return None

                    return data
            except Exception as exc:
                logger.exception("Kie.ai request error: %s", exc)
                return None

    def _parse_kie_create_response(self, text: str) -> Dict[str, Any]:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error("Kie.ai JSON decode error: %s. Response: %s", exc, text[:500])
            return {
                "error": "invalid_json",
                "message": f"JSON decode error: {exc}",
                "status_code": 0,
            }

        if not isinstance(data, dict):
            logger.error("Kie.ai non-dict response: %r", data)
            return {
                "error": "invalid_response_type",
                "message": f"Expected dict, got {type(data).__name__}",
                "status_code": 0,
            }

        code = data.get("code")
        if code != 200:
            error_msg = data.get("msg") or data.get("message") or "Unknown error"
            logger.error("Kie.ai API error code %s: %s", code, error_msg)
            return {
                "error": "api_error",
                "message": error_msg,
                "status_code": code or 0,
                "raw": data,
            }

        inner_data = data.get("data")
        if not isinstance(inner_data, dict):
            logger.error("Kie.ai data field is not dict: %r", data)
            return {
                "error": "invalid_data_structure",
                "message": "Kie.ai response data field is not a dict",
                "status_code": code,
                "raw": data,
            }

        task_id = inner_data.get("taskId") or inner_data.get("task_id")
        if not task_id:
            logger.error("No taskId in Kie.ai response: %r", data)
            return {
                "error": "no_task_id",
                "message": "Task ID missing from Kie.ai response",
                "status_code": code,
                "raw": data,
            }

        logger.info("Kie.ai task created: %s", task_id)
        return {
            "task_id": task_id,
            "status": "pending",
            "raw": data,
        }

    # ------------------------------------------------------------------
    # Normalizers
    # ------------------------------------------------------------------

    def _safe_aspect_ratio(self, aspect_ratio: str) -> str:
        return aspect_ratio if aspect_ratio in self.ASPECT_RATIOS else "16:9"

    def _safe_duration_25(self, duration: int) -> int:
        return 10 if int(duration) == 10 else 5

    def _safe_cfg_scale(self, cfg_scale: float) -> float:
        return round(
            max(self.KLING_25_CFG_MIN, min(self.KLING_25_CFG_MAX, float(cfg_scale))),
            1,
        )

    def _build_error(
        self,
        error: str,
        message: str,
        *,
        status_code: int = 0,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "error": error,
            "message": message,
            "status_code": status_code,
        }
        if extra:
            payload.update(extra)
        return payload

    # ------------------------------------------------------------------
    # Task status
    # ------------------------------------------------------------------

    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get Kie.ai task status and normalize output URL."""
        if not task_id:
            return None

        data = await self._kie_get(f"/api/v1/jobs/{task_id}")
        if not data:
            return None

        task_data = data.get("data") or {}
        status = str(task_data.get("status", "unknown")).lower()
        output = self._extract_output(task_data)

        return {
            "data": {
                "task_id": task_id,
                "status": status,
                "output": output,
            },
            "raw": data,
        }

    async def get_kie_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Backward-compatible alias."""
        return await self.get_task_status(task_id)

    def _extract_output(self, task_data: Dict[str, Any]) -> Optional[Any]:
        """Extract result URL(s) from Kie.ai task data."""
        direct_fields = ["output", "resultUrl", "result_url", "videoUrl", "imageUrl"]
        for field in direct_fields:
            value = task_data.get(field)
            if value:
                return value

        result_json = task_data.get("resultJson") or task_data.get("result_json")
        if not result_json:
            return None

        if isinstance(result_json, str):
            try:
                result_json = json.loads(result_json)
            except json.JSONDecodeError:
                logger.warning("Could not parse resultJson: %s", result_json[:300])
                return None

        if not isinstance(result_json, dict):
            return None

        for key in ("resultUrls", "result_urls", "urls", "videos", "images"):
            value = result_json.get(key)
            if isinstance(value, list) and value:
                return value[0]
            if isinstance(value, str) and value:
                return value

        return None

    # ------------------------------------------------------------------
    # Create tasks by model family
    # ------------------------------------------------------------------

    async def generate_kling_3_video(
        self,
        prompt: str,
        *,
        mode: str = "std",
        duration: int = 5,
        aspect_ratio: str = "16:9",
        image_urls: Optional[List[str]] = None,
        sound: bool = True,
        multi_shots: bool = False,
        multi_prompt: Optional[List[Dict[str, Any]]] = None,
        kling_elements: Optional[List[Dict[str, Any]]] = None,
        webhook: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate video with Kie.ai Kling 3.0."""
        if not prompt or not prompt.strip():
            return self._build_error("prompt_required", "Prompt is required")

        mode = "pro" if mode == "pro" else "std"
        duration = max(3, min(int(duration), 15))

        input_data: Dict[str, Any] = {
            "prompt": prompt[:2500],
            "sound": bool(sound),
            "duration": str(duration),
            "aspect_ratio": self._safe_aspect_ratio(aspect_ratio),
            "mode": mode,
            "multi_shots": bool(multi_shots),
        }

        cleaned_image_urls = [url for url in (image_urls or []) if url]
        if cleaned_image_urls:
            input_data["image_urls"] = cleaned_image_urls

        if kling_elements:
            input_data["kling_elements"] = kling_elements[:3]

        if multi_shots and multi_prompt:
            input_data["multi_prompt"] = multi_prompt[:6]

        payload: Dict[str, Any] = {
            "model": "kling-3.0/video",
            "input": input_data,
        }
        if webhook:
            payload["callBackUrl"] = webhook

        return await self._kie_post(self.CREATE_TASK_ENDPOINT, payload)

    async def generate_kling_25_turbo_video(
        self,
        prompt: str,
        *,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        image_url: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        cfg_scale: float = 0.5,
        webhook: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate video with Kie.ai Kling 2.5 Turbo Pro."""
        if not prompt or not prompt.strip():
            return self._build_error("prompt_required", "Prompt is required")

        model = (
            "kling/v2-5-turbo-image-to-video-pro"
            if image_url
            else "kling/v2-5-turbo-text-to-video-pro"
        )

        input_data: Dict[str, Any] = {
            "prompt": prompt[:2500],
            "duration": str(self._safe_duration_25(duration)),
            "aspect_ratio": self._safe_aspect_ratio(aspect_ratio),
            "cfg_scale": self._safe_cfg_scale(cfg_scale),
        }

        if image_url:
            input_data["image_url"] = image_url
        if negative_prompt:
            input_data["negative_prompt"] = negative_prompt[:500]

        payload: Dict[str, Any] = {
            "model": model,
            "input": input_data,
        }
        if webhook:
            payload["callBackUrl"] = webhook

        return await self._kie_post(self.CREATE_TASK_ENDPOINT, payload)

    async def generate_kling_ai_avatar(
        self,
        *,
        image_url: str,
        audio_url: str,
        prompt: str = "",
        model: str = "kling/ai-avatar-standard",
        webhook: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate talking avatar with Kie.ai Kling AI Avatar."""
        if model not in {"kling/ai-avatar-standard", "kling/ai-avatar-pro"}:
            return self._build_error(
                "unsupported_avatar_model",
                f"Unsupported Kling AI Avatar model: {model}",
            )

        if not image_url:
            return self._build_error("image_required", "Avatar image is required")
        if not audio_url:
            return self._build_error("audio_required", "Avatar audio is required")

        payload: Dict[str, Any] = {
            "model": model,
            "input": {
                "image_url": image_url,
                "audio_url": audio_url,
                "prompt": (prompt or "")[:5000],
            },
        }
        if webhook:
            payload["callBackUrl"] = webhook

        return await self._kie_post(self.CREATE_TASK_ENDPOINT, payload)

    async def create_kie_motion_task(
        self,
        input_data: Dict[str, Any],
        webhook: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create Kie.ai Kling 2.6 Motion Control task."""
        payload: Dict[str, Any] = {
            "model": "kling-2.6/motion-control",
            "input": input_data,
        }
        if webhook:
            payload["callBackUrl"] = webhook
        return await self._kie_post(self.CREATE_TASK_ENDPOINT, payload)

    async def generate_motion_control(
        self,
        *,
        image_url: str,
        video_urls: Optional[List[str]] = None,
        preset_motion: Optional[str] = None,
        prompt: Optional[str] = None,
        motion_direction: str = "video",
        mode: str = "std",
        webhook_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate motion control animation."""
        if not image_url:
            return self._build_error(
                "image_required", "Motion Control requires image_url"
            )

        cleaned_video_urls = [url for url in (video_urls or []) if url]
        if not cleaned_video_urls and not preset_motion:
            return self._build_error(
                "video_url_required",
                "Motion Control requires a movement video URL",
            )

        input_data: Dict[str, Any] = {
            "prompt": prompt or "",
            "input_urls": [image_url],
            "character_orientation": motion_direction or "video",
            "mode": "1080p" if mode == "pro" else "720p",
        }

        if cleaned_video_urls:
            input_data["video_urls"] = cleaned_video_urls
        if preset_motion:
            input_data["preset_motion"] = preset_motion

        return await self.create_kie_motion_task(input_data, webhook_url)

    # ------------------------------------------------------------------
    # Public high-level router
    # ------------------------------------------------------------------

    async def generate_video(
        self,
        prompt: str,
        model: str = "v3_std",
        duration: int = 5,
        aspect_ratio: str = "16:9",
        webhook_url: Optional[str] = None,
        image_url: Optional[str] = None,
        video_urls: Optional[List[str]] = None,
        end_image_url: Optional[str] = None,
        elements: Optional[List[Dict[str, Any]]] = None,
        negative_prompt: Optional[str] = None,
        cfg_scale: float = 0.5,
        generate_audio: bool = True,
        multi_shots: Optional[List[Dict[str, Any]]] = None,
        image_input: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Route only Kling-supported models.

        Unknown or non-Kling models return explicit errors instead of silently
        falling back to Kling 3.0. This prevents provider-routing bugs such as
        Grok image generation being sent to Kie.ai.
        """
        model = model or "v3_std"

        if model in self.NON_KLING_MODELS:
            logger.error(
                "Non-Kling model '%s' was routed to KlingService. Fix generation.py routing.",
                model,
            )
            return self._build_error(
                "wrong_provider_route",
                f"Model '{model}' must not be handled by KlingService",
                extra={"model": model},
            )

        if model in self.KLING_3_MODELS or "v3" in model or "omni" in model:
            mode = "pro" if "pro" in model else "std"
            image_urls = self._collect_image_urls(image_url, end_image_url, image_input)
            kling_elements, enhanced_prompt = self._build_kling_elements(
                elements, prompt
            )

            return await self.generate_kling_3_video(
                prompt=enhanced_prompt,
                mode=mode,
                duration=duration,
                aspect_ratio=aspect_ratio,
                image_urls=image_urls,
                sound=generate_audio,
                multi_shots=bool(multi_shots),
                multi_prompt=multi_shots,
                kling_elements=kling_elements,
                webhook=webhook_url,
            )

        if model in self.KLING_25_MODELS:
            return await self.generate_kling_25_turbo_video(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
                image_url=image_url,
                negative_prompt=negative_prompt,
                cfg_scale=cfg_scale,
                webhook=webhook_url,
            )

        if model in self.AVATAR_MODELS:
            return await self.generate_kling_ai_avatar(
                image_url=image_url or "",
                audio_url=(video_urls or [""])[0],
                prompt=prompt or "",
                model=(
                    "kling/ai-avatar-standard"
                    if model == "avatar_std"
                    else "kling/ai-avatar-pro"
                ),
                webhook=webhook_url,
            )

        if model in self.MOTION_MODELS or "motion" in model.lower():
            return await self.generate_motion_control(
                image_url=image_url or "",
                video_urls=video_urls or [],
                prompt=prompt,
                motion_direction="video",
                mode="std",
                webhook_url=webhook_url,
            )

        if model in self.GLOW_MODELS:
            return await self.generate_motion_control(
                image_url=image_url or "",
                video_urls=video_urls or [],
                preset_motion="glow",
                prompt=prompt,
                motion_direction="video",
                mode="std",
                webhook_url=webhook_url,
            )

        logger.error("Unsupported Kling model: %s", model)
        return self._build_error(
            "unsupported_model",
            f"Unsupported Kling model: {model}",
            extra={"model": model},
        )

    def _collect_image_urls(
        self,
        image_url: Optional[str],
        end_image_url: Optional[str],
        image_input: Optional[List[str]],
    ) -> List[str]:
        image_urls: List[str] = []

        for url in image_input or []:
            if url and url not in image_urls:
                image_urls.append(url)

        if image_url and image_url not in image_urls:
            image_urls.insert(0, image_url)

        if end_image_url and end_image_url not in image_urls:
            image_urls.append(end_image_url)

        return image_urls

    def _build_kling_elements(
        self,
        elements: Optional[List[Dict[str, Any]]],
        prompt: str,
    ) -> tuple[List[Dict[str, Any]], str]:
        if not elements:
            return [], prompt

        kling_elements: List[Dict[str, Any]] = []
        enhanced_prompt = prompt

        for index, element in enumerate(elements[:3]):
            urls = list(element.get("reference_image_urls") or [])
            frontal = element.get("frontal_image_url")
            if frontal:
                urls.append(frontal)

            urls = [url for url in urls if url]
            if not urls:
                continue

            name = f"element_{index}"
            kling_elements.append(
                {
                    "name": name,
                    "description": element.get(
                        "description",
                        f"reference element {index + 1}",
                    ),
                    "element_input_urls": urls[:4],
                }
            )
            enhanced_prompt += f" use @{name} as reference"

        return kling_elements, enhanced_prompt

    async def wait_for_completion(
        self,
        task_id: str,
        max_attempts: int = 60,
        delay: int = 5,
    ) -> Optional[Dict[str, Any]]:
        """Poll Kie.ai until task completion or timeout."""
        import asyncio

        for attempt in range(max_attempts):
            status = await self.get_task_status(task_id)
            if not status:
                await asyncio.sleep(delay)
                continue

            task_status = status.get("data", {}).get("status", "").lower()
            if task_status in {"completed", "succeeded", "success"}:
                logger.info("Task %s completed", task_id)
                return status

            if task_status in {"failed", "error"}:
                logger.error("Task %s failed", task_id)
                return status

            logger.debug("Task %s: %s, attempt %s", task_id, task_status, attempt + 1)
            await asyncio.sleep(delay)

        logger.warning("Task %s timeout", task_id)
        return None


from bot.config import config

kling_service = KlingService(
    kie_key=config.KIE_AI_API_KEY,
)
