import logging
from typing import Dict, List, Optional

import aiohttp

from bot.services.media_input_utils import (
    image_sources_to_data_uris,
    image_sources_to_supported_image_urls,
    is_local_upload_source,
)
from bot.services.kie_file_upload_service import kie_file_upload_service
from bot.services.kie_market_service import kie_market_service

logger = logging.getLogger(__name__)
MAX_IMAGE_INPUTS = 8
NANO_BANANA_2_LITE_MODEL_IDS = {
    "nano-banana-2-lite",
    "nano_banana_2_lite",
    "banana_2_lite",
}
RESOLUTION_ALIASES = {
    "BASIC": "2K",
    "HIGH": "4K",
    "1K": "1K",
    "2K": "2K",
    "4K": "4K",
}


def _normalize_resolution(resolution: str) -> str:
    raw = str(resolution or "2K").strip().upper()
    normalized = RESOLUTION_ALIASES.get(raw, raw)
    if normalized not in {"1K", "2K", "4K"}:
        logger.warning(
            "Nano Banana 2 unsupported resolution %s, fallback to 2K",
            resolution,
        )
        return "2K"
    if normalized != raw:
        logger.info(
            "Nano Banana 2 resolution normalized: %s -> %s", raw, normalized
        )
    return normalized


class ProviderClient:
    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=120)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _post(self, endpoint: str, payload: Dict) -> Optional[Dict]:
        session = await self._get_session()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with session.post(
                f"{self.base_url}{endpoint}", headers=headers, json=payload
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    error = await resp.text()
                    logger.warning(
                        "Nano Banana 2 POST failed on provider %s: %s - %s",
                        self.base_url,
                        resp.status,
                        error,
                    )
                    return None
        except Exception as e:
            logger.warning("Nano Banana 2 POST error on provider %s: %s", self.base_url, e)
            return None

    async def _get(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        session = await self._get_session()
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with session.get(
                f"{self.base_url}{endpoint}", headers=headers, params=params
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    error = await resp.text()
                    if resp.status != 404:
                        logger.warning(
                            "Nano Banana 2 GET failed on provider %s: %s - %s",
                            self.base_url,
                            resp.status,
                            error,
                        )
                    else:
                        logger.debug(
                            "Nano Banana 2 GET 404 on provider %s (expected for non-existent task)",
                            self.base_url,
                        )
                    return None
        except Exception as e:
            logger.warning("Nano Banana 2 GET error on provider %s: %s", self.base_url, e)
            return None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


class NanoBanana2Service:
    def __init__(
        self,
        primary_provider: ProviderClient,
        fallback_provider: Optional = None,
    ):
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider

    async def _post(self, endpoint: str, payload: Dict) -> Optional[Dict]:
        resp = None
        if hasattr(self.primary_provider, "_post"):
            resp = await self.primary_provider._post(endpoint, payload)
        if resp is not None:
            return resp
        if self.fallback_provider is not None and hasattr(self.fallback_provider, "_post"):
            logger.info("Falling back to secondary provider for Nano Banana 2 POST %s", endpoint)
            return await self.fallback_provider._post(endpoint, payload)
        return None

    async def _get(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        resp = None
        if hasattr(self.primary_provider, "_get"):
            resp = await self.primary_provider._get(endpoint, params)
        if resp is not None:
            return resp
        if self.fallback_provider is not None and hasattr(self.fallback_provider, "_get"):
            logger.info("Falling back to secondary provider for Nano Banana 2 GET %s", endpoint)
            return await self.fallback_provider._get(endpoint, params)
        return None

    async def create_task(
        self,
        prompt: str,
        image_input: List[str] = None,
        aspect_ratio: str = "1:1",
        resolution: str = "2K",
        output_format: str = "png",
        callback_url: str = None,
        model: str = "nano-banana-2",
    ) -> Optional[str]:
        if not prompt and not image_input:
            logger.warning("Nano Banana 2 create_task: no prompt and no image_input")
            return None

        uploaded_image_urls = await kie_file_upload_service.upload_local_image_sources(
            image_input or []
        )
        supported_image_urls = image_sources_to_supported_image_urls(uploaded_image_urls)

        if supported_image_urls:
            normalized_image_input = supported_image_urls
        elif image_input:
            normalized_image_input = image_sources_to_data_uris(image_input)
        else:
            normalized_image_input = []

        if str(model or "").strip() in NANO_BANANA_2_LITE_MODEL_IDS:
            try:
                logger.info(
                    "Nano Banana 2 Lite create_task: refs=%s aspect_ratio=%s model=nano-banana-2-lite",
                    len(normalized_image_input),
                    aspect_ratio,
                )
                return await kie_market_service.create_nano_banana_2_lite_task(
                    prompt=prompt,
                    image_urls=normalized_image_input[:10],
                    aspect_ratio=aspect_ratio or "auto",
                    callback_url=callback_url,
                )
            except Exception as exc:
                logger.error("Nano Banana 2 Lite create_task failed: %s", exc)
                return None

        normalized_resolution = _normalize_resolution(resolution)
        payload = {
            "model": "nano-banana-2",
            "input": {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "resolution": normalized_resolution,
                "output_format": output_format,
            },
        }
        if normalized_image_input:
            payload["input"]["image_input"] = normalized_image_input
        if callback_url:
            payload["callBackUrl"] = callback_url

        transport = (
            "kie_file_upload_urls"
            if uploaded_image_urls != supported_image_urls
            else "image_input_urls"
        )
        logger.info(
            "Nano Banana 2 create_task: refs=%s aspect_ratio=%s resolution=%s transport=%s model=%s",
            len(normalized_image_input),
            aspect_ratio,
            resolution,
            transport if normalized_image_input else "none",
            payload["model"],
        )

        resp = await self._post("/api/v1/jobs/createTask", payload)
        if not resp or not isinstance(resp, dict):
            logger.error(f"Nano Banana 2 create_task failed, resp: {resp}")
            return None
        data = resp.get("data")
        if not isinstance(data, dict):
            logger.error(f"Nano Banana 2 invalid data: {data} (full resp: {resp})")
            return None
        task_id = data.get("taskId")
        if not task_id:
            logger.error(f"No taskId in response: {resp}")
        return task_id

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        resp = await self._get("/api/v1/jobs/recordInfo", params={"taskId": task_id})
        if not resp or not isinstance(resp, dict):
            return None
        data = resp.get("data")
        if not isinstance(data, dict):
            logger.warning(f"Nano Banana 2 status invalid data: {data}")
            return None
        return data

    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "auto",
        resolution: str = "4K",
        image_input: List[str] = None,
        output_format: str = "png",
        callback_url: str = None,
        model: str = "nano-banana-2",
    ) -> Optional[Dict]:
        if str(model or "").strip() in NANO_BANANA_2_LITE_MODEL_IDS:
            task_id = await self.create_task(
                prompt,
                image_input,
                aspect_ratio,
                resolution,
                output_format,
                callback_url,
                model=model,
            )
            return {"task_id": task_id} if task_id else None

        if hasattr(self.primary_provider, "generate_image"):
            result = await self.primary_provider.generate_image(
                prompt, aspect_ratio, resolution, image_input, output_format
            )
            if result is not None:
                if isinstance(result, (bytes, bytearray)):
                    return {"image_bytes": bytes(result)}
                return result
            logger.info(
                "Nano Banana 2: primary sync provider failed, trying queued provider path"
            )

        task_id = await self.create_task(
            prompt, image_input, aspect_ratio, resolution, output_format, callback_url
        )
        if task_id:
            return {"task_id": task_id}

        if self.fallback_provider is not None and hasattr(self.fallback_provider, "generate_image"):
            logger.info(
                "Nano Banana 2: falling back to secondary provider generate_image "
                "(primary create_task failed)"
            )
            result = await self.fallback_provider.generate_image(
                prompt, aspect_ratio, resolution, image_input, output_format
            )
            if result is not None:
                return {"image_bytes": result}
        return None

    async def wait_for_completion(
        self, task_id: str, max_attempts: int = 60, delay: float = 5.0
    ) -> Optional[Dict]:
        import asyncio
        import json

        consecutive_failures = 0
        for attempt in range(max_attempts):
            status = await self.get_task_status(task_id)
            if status is None:
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    logger.error(
                        f"Task {task_id} not found/failed after {consecutive_failures} consecutive errors"
                    )
                    return None
                await asyncio.sleep(delay)
                continue
            consecutive_failures = 0
            task_state = status.get("state", "").lower()
            if task_state == "success":
                return status
            elif task_state == "fail":
                logger.error(
                    f"Task {task_id} failed: {status.get('failMsg', 'Unknown')}"
                )
                return None
            await asyncio.sleep(delay)
        logger.warning(f"Task {task_id} timeout after {max_attempts} attempts")
        return None

    async def close(self):
        await self.primary_provider.close()
        if self.fallback_provider is not None:
            await self.fallback_provider.close()


from bot.config import config


class NanoBanana2GeminiProvider:
    """Gemini-совместимый fallback провайдер для Nano Banana 2 (api.apiyi.com).

    Использует проприетарный imageConfig для управления разрешением.
    """

    DETAIL_ENHANCER_PROMPT = """
ULTRA DETAIL & QUALITY BOOST:
• Ultra-detailed high resolution, crystal clear image
• Intricate textures, fine details everywhere
• Sharp focus, natural lighting, depth of field
• Photorealistic quality, precise features
• Professional photography quality, high bitrate
"""

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=120)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "auto",
        resolution: str = "4K",
        image_input: List[str] = None,
        output_format: str = "png",
    ) -> Optional[bytes]:
        session = await self._get_session()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        enhanced_prompt = f"{prompt}\n\n{self.DETAIL_ENHANCER_PROMPT}"
        parts = [{"text": enhanced_prompt}]
        if image_input:
            for source in image_input:
                if isinstance(source, str) and source.startswith("data:image/"):
                    try:
                        header, b64data = source.split(",", 1)
                        mime_type = header.replace("data:", "").split(";")[0]
                        parts.append({
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": b64data,
                            }
                        })
                    except Exception:
                        logger.warning("Nano Banana 2 Gemini provider: failed to parse data URI")
                elif isinstance(source, str) and source.startswith(("http://", "https://")):
                    try:
                        async with session.get(source) as img_resp:
                            if img_resp.status == 200:
                                img_data = await img_resp.read()
                                import base64
                                b64data = base64.b64encode(img_data).decode("utf-8")
                                mime_type = img_resp.content_type or "image/jpeg"
                                parts.append({
                                    "inlineData": {
                                        "mimeType": mime_type,
                                        "data": b64data,
                                    }
                                })
                            else:
                                logger.warning(
                                    "Nano Banana 2 Gemini provider: failed to fetch remote reference %s",
                                    source,
                                )
                    except Exception:
                        logger.warning(
                            "Nano Banana 2 Gemini provider: failed to fetch remote reference %s",
                            source,
                        )

        normalized_resolution = _normalize_resolution(resolution)
        image_size = normalized_resolution  # "1K", "2K" или "4K"

        # api.apiyi.com использует imageConfig (НЕ стандартный Gemini imageSize)
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {
                    "aspectRatio": aspect_ratio,
                    "imageSize": image_size,
                },
            },
        }

        model = "gemini-3.1-flash-image-preview"
        url = f"{self.base_url}/models/{model}:generateContent"

        try:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        for part in parts:
                            if "inlineData" in part:
                                import base64
                                img_b64 = part["inlineData"]["data"]
                                img_bytes = base64.b64decode(img_b64)
                                logger.info(
                                    "Nano Banana 2 Gemini provider: image %d bytes, size=%s, mime=%s",
                                    len(img_bytes),
                                    image_size,
                                    part["inlineData"].get("mimeType", "unknown"),
                                )
                                return img_bytes
                    logger.warning(
                        "Nano Banana 2 Gemini provider: no inlineData in response"
                    )
                    return None
                else:
                    error = await resp.text()
                    logger.warning(
                        "Nano Banana 2 Gemini provider POST failed: %s - %s",
                        resp.status,
                        error,
                    )
                    return None
        except Exception as e:
            logger.warning(
                "Nano Banana 2 Gemini provider error: %s", e
            )
            return None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


# --- Инициализация: prefer Gemini-compatible APIYI, fallback to kie.ai ---

_kie_provider = ProviderClient(
    api_key=config.KIE_AI_API_KEY or config.NANOBANANA_API_KEY,
    base_url="https://api.kie.ai",
)

_gemini_provider = None
if config.NANOBANANA2_FALLBACK_API_KEY and config.NANOBANANA2_FALLBACK_BASE_URL:
    _gemini_provider = NanoBanana2GeminiProvider(
        api_key=config.NANOBANANA2_FALLBACK_API_KEY,
        base_url=config.NANOBANANA2_FALLBACK_BASE_URL,
    )

if _gemini_provider:
    logger.info(
        "Nano Banana 2: using APIYI Gemini-compatible provider as primary, kie.ai as fallback"
    )
    nano_banana_2_service = NanoBanana2Service(
        primary_provider=_gemini_provider,
        fallback_provider=_kie_provider,
    )
else:
    logger.info("Nano Banana 2: using kie.ai as primary")
    nano_banana_2_service = NanoBanana2Service(
        primary_provider=_kie_provider,
        fallback_provider=None,
    )
