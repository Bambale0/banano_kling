"""
Kling API Service - PiAPI Kling 3.0 (Freepik completely removed)

Endpoints:
- POST /api/v1/task - Create task
- GET /api/v1/task - List tasks
- GET /api/v1/task/{task_id} - Get task status

Docs: kling_api.md
"""

import asyncio
import base64
import logging
import os
from typing import Any, Dict, List, Optional

import aiohttp

# Optional Replicate SDK. We import lazily and tolerate its absence so the
# service can continue using the legacy PiAPI flow when REPLICATE_API_TOKEN is
# not provided or the package isn't installed in the environment.
try:
    import replicate
except Exception:  # pragma: no cover - optional dependency
    replicate = None

logger = logging.getLogger(__name__)


class KlingService:
    """Сервис для работы с PiAPI Kling 3.0 API"""

    ENDPOINTS = {
        "task": "/api/v1/task",
    }

    ASPECT_RATIOS = ["16:9", "9:16", "1:1"]
    DURATIONS = list(range(3, 16))

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.piapi.ai",
        replicate_token: Optional[str] = None,
    ):
        """Initialize KlingService.

        If replicate_token is provided and the replicate SDK is available the
        service will prefer Replicate for supported task types. Otherwise it
        will fall back to the legacy PiAPI HTTP flow.
        """
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

        # Replicate configuration
        self.replicate_token = replicate_token or os.environ.get("REPLICATE_API_TOKEN")
        self.replicate_enabled = bool(self.replicate_token and replicate)
        self.replicate_client = None
        if self.replicate_enabled:
            # Prefer Client API when available, otherwise rely on module-level
            # functions which use the REPLICATE_API_TOKEN env var.
            try:
                if hasattr(replicate, "Client"):
                    self.replicate_client = replicate.Client(
                        api_token=self.replicate_token
                    )
                else:
                    # replicate module will read token from env var
                    os.environ.setdefault("REPLICATE_API_TOKEN", self.replicate_token)
                    self.replicate_client = replicate
            except Exception:
                # If client creation failed, disable replicate usage
                logger.exception(
                    "Failed to initialize Replicate client, falling back to PiAPI"
                )
                self.replicate_enabled = False

    async def _post(self, url: str, payload: Dict) -> Optional[Dict]:
        if not self.headers:
            logger.error("API key not configured")
            return None
        # Make the POST request
        async with aiohttp.ClientSession(trust_env=False) as session:
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

    # ----------------------------- Replicate helpers -----------------------------
    async def _replicate_create_prediction(
        self, model: str, input_data: Dict, webhook: Optional[str] = None
    ) -> Optional[Dict]:
        """Create a Replicate prediction in a thread-safe manner.

        Returns a dict with at least 'task_id' and 'status'.
        """
        if not self.replicate_enabled:
            logger.error("Replicate not configured")
            return None

        def _create():
            client = self.replicate_client or replicate
            kwargs = {"model": model, "input": input_data}
            if webhook:
                kwargs.update(
                    {"webhook": webhook, "webhook_events_filter": ["completed"]}
                )
            pred = client.predictions.create(**kwargs)
            return pred

        try:
            pred = await asyncio.to_thread(_create)
        except Exception:
            logger.exception("Replicate prediction creation failed")
            return None

        # prediction object can be dict-like or custom object; normalize
        pred_id = getattr(pred, "id", None) or (
            pred.get("id") if isinstance(pred, dict) else None
        )
        status = getattr(pred, "status", None) or (
            pred.get("status") if isinstance(pred, dict) else None
        )
        return {"task_id": pred_id, "status": status, "raw": pred}

    async def _replicate_get_prediction(self, prediction_id: str) -> Optional[Dict]:
        if not self.replicate_enabled:
            logger.error("Replicate not configured")
            return None

        def _get():
            client = self.replicate_client or replicate
            return client.predictions.get(prediction_id)

        try:
            pred = await asyncio.to_thread(_get)
        except Exception:
            logger.exception("Failed to fetch replicate prediction")
            return None

        # Normalize to structure similar to PiAPI get_task_status
        pred_id = getattr(pred, "id", None) or (
            pred.get("id") if isinstance(pred, dict) else None
        )
        status = getattr(pred, "status", None) or (
            pred.get("status") if isinstance(pred, dict) else None
        )
        output = getattr(pred, "output", None) or (
            pred.get("output") if isinstance(pred, dict) else None
        )
        return {
            "data": {"task_id": pred_id, "status": status, "output": output},
            "raw": pred,
        }

    async def _replicate_cancel(self, prediction_id: str) -> Optional[Dict]:
        if not self.replicate_enabled:
            logger.error("Replicate not configured")
            return None

        def _cancel():
            client = self.replicate_client or replicate
            # Try nice API first
            try:
                if hasattr(client.predictions, "cancel"):
                    return client.predictions.cancel(prediction_id)
            except Exception:
                pass
            # Fallback: fetch object and call cancel() if available
            try:
                pred = client.predictions.get(prediction_id)
                if hasattr(pred, "cancel"):
                    return pred.cancel()
            except Exception:
                pass
            raise RuntimeError("Cancel not supported by replicate client")

        try:
            res = await asyncio.to_thread(_cancel)
            return {"ok": True, "raw": res}
        except Exception:
            logger.exception("Failed to cancel replicate prediction")
            return None

    async def _get(self, url: str, params: Optional[Dict] = None) -> Optional[Dict]:
        if not self.headers:
            logger.error("API key not configured")
            return None
        async with aiohttp.ClientSession(trust_env=False) as session:
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

        def _convert_bytes_to_data_uri(obj):
            # Recursively convert bytes values inside structures to data URI strings
            if isinstance(obj, (bytes, bytearray)):
                return f"data:image/png;base64,{base64.b64encode(obj).decode('utf-8')}"
            if isinstance(obj, dict):
                return {k: _convert_bytes_to_data_uri(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_convert_bytes_to_data_uri(v) for v in obj]
            return obj

        safe_input = _convert_bytes_to_data_uri(input_data)

        payload = {
            "model": "kling",
            "task_type": task_type,
            "input": safe_input,
        }
        if config:
            payload["config"] = config
        return await self._post(url, payload)

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        # Prefer Replicate lookup when enabled (non-destructive). If it fails
        # or returns no useful information, fall back to the legacy PiAPI HTTP
        # endpoint so hybrid mode works during migration.
        if self.replicate_enabled:
            rep = await self._replicate_get_prediction(task_id)
            if rep:
                return rep
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

        def _maybe_data_uri(v):
            # Convert bytes to data URI expected by Kling (assume png)
            if isinstance(v, (bytes, bytearray)):
                return f"data:image/png;base64,{base64.b64encode(v).decode('utf-8')}"
            return v

        input_data = {
            "prompt": prompt,
            "version": "3.0",
            "mode": mode,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "enable_audio": enable_audio,
            "prefer_multi_shots": prefer_multi_shots,
            # Hint Kling to prefer direct HTTP fetching of provided URLs
            # (helps when Kling's resumable upload/resume flow fails)
            "prefer_http": True,
        }
        if image_url:
            input_data["image_url"] = _maybe_data_uri(image_url)
        if image_tail_url:
            input_data["image_tail_url"] = _maybe_data_uri(image_tail_url)
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
        def _maybe_data_uri(v):
            if isinstance(v, (bytes, bytearray)):
                return f"data:image/png;base64,{base64.b64encode(v).decode('utf-8')}"
            return v

        # If Replicate configured - use the official Replicate SDK and model
        # kwaivgi/kling-v2.6-motion-control. Map PiAPI-style fields to the
        # model input schema.
        input_data = {
            # Replicate accepts 'image' and 'video' keys
            "image": _maybe_data_uri(image_url) if image_url else None,
            "video": video_url if video_url else None,
            "mode": mode,
            "prompt": prompt,
            "keep_original_sound": keep_original_sound,
            # character_orientation / motion_direction mapping
            "character_orientation": motion_direction,
        }

        # Remove None entries
        input_data = {k: v for k, v in input_data.items() if v is not None}

        if self.replicate_enabled:
            webhook = webhook_url or os.environ.get("REPLICATE_WEBHOOK_URL")
            # Prefer service's configured webhook if none provided
            if not webhook and hasattr(__import__("bot.config"), "config"):
                try:
                    from bot.config import config as _config

                    webhook = webhook_url or _config.replicate_notification_url
                except Exception:
                    webhook = webhook_url

            pred = await self._replicate_create_prediction(
                model="kwaivgi/kling-v2.6-motion-control",
                input_data=input_data,
                webhook=webhook,
            )
            return pred

        # Fallback to legacy PiAPI task creation for environments without Replicate
        input_piapi = {
            "image_url": _maybe_data_uri(image_url) if image_url else None,
            "mode": mode,
            "motion_direction": motion_direction,
            "keep_original_sound": keep_original_sound,
            # Ask Kling to prefer direct HTTP fetch for the image
            "prefer_http": True,
        }
        if video_url:
            input_piapi["video_url"] = video_url
        if preset_motion:
            input_piapi["preset_motion"] = preset_motion
        if prompt:
            input_piapi["prompt"] = prompt
        config = {"service_mode": service_mode}
        if webhook_url:
            config["webhook_config"] = {"endpoint": webhook_url, "secret": ""}
        return await self.create_task("motion_control", input_piapi, config)

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
        def _maybe_data_uri(v):
            if isinstance(v, (bytes, bytearray)):
                return f"data:image/png;base64,{base64.b64encode(v).decode('utf-8')}"
            return v

        input_data = {
            "prompt": prompt,
            "version": version,
            "resolution": resolution,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "enable_audio": enable_audio,
            # Prefer direct HTTP fetch when Kling receives external image URLs
            "prefer_http": True,
        }
        if multi_shots:
            input_data["multi_shots"] = multi_shots
        if images:
            # Convert any bytes images to data URIs
            input_data["images"] = [_maybe_data_uri(i) for i in images]
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
