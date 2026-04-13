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
import json
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
        "task": "/api/v1/jobs",
    }

    KIE_BASE_URL = "https://api.kie.ai"

    ASPECT_RATIOS = ["16:9", "9:16", "1:1"]
    DURATIONS = list(range(3, 16))

    def __init__(
        self,
        kie_key: Optional[str] = None,
    ):
        """Initialize KlingService with Kie.ai only."""
        self.kie_key = kie_key or os.getenv("KIE_AI_API_KEY")
        self.kie_headers = (
            {
                "Authorization": f"Bearer {self.kie_key}",
                "Content-Type": "application/json",
            }
            if self.kie_key
            else None
        )

    async def _kie_post(self, endpoint: str, payload: Dict) -> Optional[Dict]:
        """POST to Kie.ai API"""
        if not self.kie_headers:
            logger.error("Kie.ai API key not configured")
            return None
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
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError as e:
                        logger.error(
                            f"Kie.ai JSON decode error: {e}. Response text: {text[:300]}..."
                        )
                        return {
                            "error": "invalid_json",
                            "message": f"JSON decode error: {str(e)}",
                        }
                    if not isinstance(data, dict):
                        logger.error(
                            f"Kie.ai non-dict response: type={type(data)}, content={data}. Text: {text[:300]}..."
                        )
                        return {
                            "error": "invalid_response_type",
                            "message": f"Expected dict, got {type(data)}",
                        }
                    code = data.get("code")
                    if code != 200:
                        error_msg = data.get("msg", "Unknown error")
                        logger.error(f"Kie.ai API error code {code}: {error_msg}")
                        return {
                            "error": "api_error",
                            "message": error_msg,
                            "status_code": code,
                        }
                    inner_data = data.get("data")
                    if not isinstance(inner_data, dict):
                        logger.error(
                            f"Kie.ai 'data' field not dict: type={type(inner_data)}, data={data}. Text: {text[:300]}..."
                        )
                        return {
                            "error": "invalid_data_structure",
                            "message": f"data field not dict",
                        }
                    task_id = inner_data.get("taskId")
                    if task_id is None:
                        logger.error(f"No taskId in Kie.ai response. Full data: {data}")
                        return {
                            "error": "no_task_id",
                            "message": "Task ID missing from response",
                        }
                    logger.info(f"Kie.ai task created: {task_id}")
                    return {
                        "task_id": task_id,
                        "status": "pending",
                    }
            except Exception as e:
                logger.exception(f"Kie.ai request error: {e}")
                return {
                    "error": "network_error",
                    "message": f"Network error: {str(e)}",
                    "status_code": 0,
                }

    async def _kie_get(
        self, endpoint: str, params: Optional[Dict] = None
    ) -> Optional[Dict]:
        """GET from Kie.ai API"""
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
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.error(f"Kie.ai API error {resp.status}")
                        return None
            except Exception as e:
                logger.exception(f"Kie.ai request error: {e}")
                return None

    async def create_kie_motion_task(
        self, input_data: Dict, webhook: Optional[str] = None
    ) -> Optional[Dict]:
        """Create Kie.ai motion control task"""
        payload = {
            "model": "kling-2.6/motion-control",
            "input": input_data,
        }
        if webhook:
            payload["callBackUrl"] = webhook
        return await self._kie_post("/api/v1/jobs/createTask", payload)

    async def get_kie_task_status(self, task_id: str) -> Optional[Dict]:
        """Get Kie.ai task status"""
        endpoint = f"/api/v1/jobs/{task_id}"
        data = await self._kie_get(endpoint)
        if data:
            status = data.get("data", {}).get("status", "unknown").lower()
            # Parse resultJson for output URLs
            result_json_str = data.get("data", {}).get("resultJson", "{}")
            try:
                import json

                result_json = json.loads(result_json_str)
                result_urls = result_json.get("resultUrls", [])
                output = result_urls[0] if result_urls else None
            except (json.JSONDecodeError, KeyError):
                output = None
            return {
                "data": {
                    "task_id": task_id,
                    "status": status,
                    "output": output,
                },
                "raw": data,
            }
        return None

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

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        """Get Kie.ai task status"""
        endpoint = f"/api/v1/jobs/{task_id}"
        data = await self._kie_get(endpoint)
        if data:
            status = data.get("data", {}).get("status", "unknown").lower()
            # Parse resultJson for output URLs
            result_json_str = data.get("data", {}).get("resultJson", "{}")
            try:
                import json

                result_json = json.loads(result_json_str)
                result_urls = result_json.get("resultUrls", [])
                output = result_urls[0] if result_urls else None
            except (json.JSONDecodeError, KeyError):
                output = None
            return {
                "data": {
                    "task_id": task_id,
                    "status": status,
                    "output": output,
                },
                "raw": data,
            }
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
        video_urls: Optional[List[str]] = None,
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

        # Kie.ai primary (new migration target)
        if self.kie_key:
            kie_input = {
                "prompt": prompt or "",
                "input_urls": [_maybe_data_uri(image_url)],
                "video_urls": [_maybe_data_uri(v) for v in (video_urls or [])],
                "character_orientation": motion_direction,
                "mode": "720p" if mode == "std" else "1080p",
            }
            if not kie_input["video_urls"]:
                return {
                    "error": "video_url_required",
                    "message": "Video URL is required for Kie.ai motion control",
                }
            webhook = (
                webhook_url or "https://your-domain.com/api/callback"
            )  # use config if available
            pred = await self.create_kie_motion_task(kie_input, webhook)
            if pred:
                return pred

        # Fallback: Replicate (existing)
        input_data = {
            # Replicate accepts 'image' and 'video' keys
            "image": _maybe_data_uri(image_url) if image_url else None,
            "video": _maybe_data_uri(video_urls[0]) if video_urls else None,
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

        # Legacy PiAPI fallback (deprecated)
        logger.warning("Using legacy PiAPI motion control - migrate to Kie.ai")
        input_piapi = {
            "image_url": _maybe_data_uri(image_url) if image_url else None,
            "mode": mode,
            "motion_direction": motion_direction,
            "keep_original_sound": keep_original_sound,
            # Ask Kling to prefer direct HTTP fetch for the image
            "prefer_http": True,
        }
        if video_urls:
            input_piapi["video_url"] = video_urls[0]
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

    async def generate_kling_3_video(
        self,
        prompt: str,
        mode: str = "std",
        duration: int = 5,
        aspect_ratio: str = "16:9",
        image_urls: Optional[List[str]] = None,
        sound: bool = False,
        multi_shots: bool = False,
        multi_prompt: Optional[List[Dict[str, Any]]] = None,
        kling_elements: Optional[List[Dict[str, Any]]] = None,
        webhook: Optional[str] = None,
    ) -> Optional[Dict]:
        """Generate video using Kie.ai Kling 3.0 API"""
        if not self.kie_key:
            logger.error("Kie.ai API key not configured for Kling 3.0")
            return None

        input_data = {
            "prompt": prompt,
            "sound": sound,
            "duration": str(duration),
            "aspect_ratio": aspect_ratio,
            "mode": mode,
            "multi_shots": multi_shots,
        }
        if image_urls:
            input_data["image_urls"] = image_urls
        if kling_elements:
            input_data["kling_elements"] = kling_elements
        if multi_shots and multi_prompt:
            input_data["multi_prompt"] = multi_prompt

        payload = {
            "model": "kling-3.0/video",
            "input": input_data,
        }
        if webhook:
            payload["callBackUrl"] = webhook

        return await self._kie_post("/api/v1/jobs/createTask", payload)

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
        elements: Optional[List[Dict]] = None,
        negative_prompt: Optional[str] = None,
        cfg_scale: float = 0.5,
        generate_audio: bool = True,
        multi_shots: Optional[List[Dict[str, Any]]] = None,
        image_input: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        if model == "seedance2":
            input_data = {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "duration": duration,
                "generate_audio": generate_audio,
                "resolution": "720p",
                "nsfw_checker": False,
                "web_search": False,
            }
            if image_url:
                input_data["first_frame_url"] = image_url
            if end_image_url:
                input_data["last_frame_url"] = end_image_url
            if image_input:
                input_data["reference_image_urls"] = image_input[:9]
            if video_url:
                input_data["reference_video_urls"] = [video_url]
            payload = {
                "model": "bytedance/seedance-2",
                "input": input_data,
            }
            if webhook_url:
                payload["callBackUrl"] = webhook_url
            return await self._kie_post("/api/v1/jobs/createTask", payload)

        # Kling 3.0 migration: prefer Kie.ai API
        if "v3" in model or "omni" in model:
            # Map model to mode
            mode = "pro" if "pro" in model else "std"

            # Prepare image_urls including references (first/last + image_input)
            image_urls = image_input[:] if image_input else []
            if image_url and image_url not in image_urls:
                image_urls.insert(0, image_url)
            if end_image_url and end_image_url not in image_urls:
                image_urls.append(end_image_url)

            # Map elements to kling_elements
            kling_elements = []
            if elements:
                for i, el in enumerate(elements[:3]):  # max 3 elements
                    urls = el.get("reference_image_urls", [])
                    frontal = el.get("frontal_image_url")
                    if frontal:
                        urls.append(frontal)
                    if len(urls) >= 1:
                        kling_elements.append(
                            {
                                "name": f"element_{i}",
                                "description": el.get(
                                    "description", f"reference element {i+1}"
                                ),
                                "element_input_urls": urls[:4],
                            }
                        )
                        # Enhance prompt to reference the element
                        prompt += f" use @{kling_elements[-1]['name']} as reference"

            # Multi-shot support
            kling_multi_shots = bool(multi_shots)
            kling_multi_prompt = multi_shots

            return await self.generate_kling_3_video(
                prompt=prompt,
                mode=mode,
                duration=duration,
                aspect_ratio=aspect_ratio,
                image_urls=image_urls,
                sound=generate_audio,
                multi_shots=kling_multi_shots,
                multi_prompt=kling_multi_prompt,
                kling_elements=kling_elements,
                webhook=webhook_url,
            )

        elif "motion" in model.lower():
            return await self.generate_motion_control(
                image_url=image_url,
                video_url=video_urls[0] if video_urls else None,
                prompt=prompt if negative_prompt is None else prompt,
                aspect_ratio=aspect_ratio,
                webhook_url=webhook_url,
            )
        elif model == "kling-2.6/motion-control":
            return await self.create_kie_motion_task(
                {
                    "prompt": prompt,
                    "input_urls": [image_url],
                    "video_urls": video_urls or [],
                    "character_orientation": "video",  # default
                    "mode": "720p",  # default
                },
                webhook_url,
            )
        else:
            if model == "grok_imagine":
                logger.error(
                    "Direct call to kling_service.generate_video with 'grok_imagine' not supported. Use generation handler."
                )
                return {
                    "error": "model_not_supported_direct",
                    "message": "Grok Imagine via handler only",
                }
            logger.warning(
                f"Unknown Kling model '{model}', falling back to std Kling 3.0"
            )
            return await self.generate_kling_3_video(
                prompt=prompt,
                mode="std",
                duration=duration,
                aspect_ratio=aspect_ratio,
                sound=generate_audio,
                webhook=webhook_url,
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
    kie_key=config.KIE_AI_API_KEY,
)
