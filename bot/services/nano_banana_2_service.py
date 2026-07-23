import asyncio
import base64
import json
import logging
from typing import Any, Dict, List, Optional

import aiohttp

from bot.config import config
from bot.services.kie_file_upload_service import kie_file_upload_service
from bot.services.kie_market_service import kie_market_service
from bot.services.media_input_utils import (
    image_sources_to_data_uris,
    image_sources_to_supported_image_urls,
)

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

# Older handlers wrapped the real user prompt in a long identity-preservation
# instruction. That wrapper noticeably changes APIYI/Gemini output compared with
# the provider playground, so APIYI receives the original user request instead.
_LEGACY_EDIT_PREFIX = "EDIT REQUEST (highest priority):"
_LEGACY_REFERENCE_MARKER = "\n\nReference guidance:"
_LEGACY_REFERENCE_ONLY_PREFIX = "Reference guidance:"
_REFERENCE_ONLY_PROMPT = (
    "Use the uploaded image as the visual reference. Preserve the person's natural "
    "identity and facial features without beautifying, caricaturing, or smoothing the face."
)


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
            "Nano Banana 2 resolution normalized: %s -> %s",
            raw,
            normalized,
        )
    return normalized


def _normalize_apiyi_prompt(prompt: str) -> tuple[str, bool]:
    """Return the user prompt without legacy bot-side prompt engineering.

    APIYI is intentionally the primary Nano Banana 2 provider. To keep its result
    close to the APIYI playground, the service must not append quality boosters or
    forward the old verbose ``Reference guidance`` wrapper.
    """

    value = str(prompt or "").strip()
    if not value:
        return "", False

    if value.startswith(_LEGACY_EDIT_PREFIX):
        user_request = value[len(_LEGACY_EDIT_PREFIX) :].lstrip()
        if _LEGACY_REFERENCE_MARKER in user_request:
            user_request = user_request.split(_LEGACY_REFERENCE_MARKER, 1)[0].rstrip()
        if user_request:
            return user_request, user_request != value

    if value.startswith(_LEGACY_REFERENCE_ONLY_PREFIX):
        return _REFERENCE_ONLY_PROMPT, True

    return value, False


def _extract_inline_image(result: Dict[str, Any]) -> tuple[bytes, str] | None:
    candidates = result.get("candidates") or []
    if not isinstance(candidates, list):
        return None

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content") or {}
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            inline_data = part.get("inlineData") or part.get("inline_data")
            if not isinstance(inline_data, dict):
                continue
            encoded = inline_data.get("data")
            if not isinstance(encoded, str) or not encoded:
                continue
            try:
                return (
                    base64.b64decode(encoded),
                    str(inline_data.get("mimeType") or inline_data.get("mime_type") or "unknown"),
                )
            except Exception:
                logger.exception("Nano Banana 2 APIYI returned invalid base64 image data")
    return None


class ProviderClient:
    """Queued Kie.ai client used as the fallback for APIYI."""

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=120)
            )
        return self._session

    async def _post(self, endpoint: str, payload: Dict) -> Optional[Dict]:
        session = await self._get_session()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with session.post(
                f"{self.base_url}{endpoint}",
                headers=headers,
                json=payload,
            ) as resp:
                body = await resp.text()
                if resp.status == 200:
                    try:
                        parsed = json.loads(body)
                    except json.JSONDecodeError:
                        logger.warning("Nano Banana 2 Kie response is not JSON")
                        return None
                    return parsed if isinstance(parsed, dict) else None

                logger.warning(
                    "Nano Banana 2 POST failed on provider %s: %s - %s",
                    self.base_url,
                    resp.status,
                    body[:1000],
                )
                return None
        except Exception as exc:
            logger.warning(
                "Nano Banana 2 POST error on provider %s: %s",
                self.base_url,
                exc,
            )
            return None

    async def _get(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        session = await self._get_session()
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with session.get(
                f"{self.base_url}{endpoint}",
                headers=headers,
                params=params,
            ) as resp:
                body = await resp.text()
                if resp.status == 200:
                    try:
                        parsed = json.loads(body)
                    except json.JSONDecodeError:
                        logger.warning("Nano Banana 2 Kie status response is not JSON")
                        return None
                    return parsed if isinstance(parsed, dict) else None

                if resp.status != 404:
                    logger.warning(
                        "Nano Banana 2 GET failed on provider %s: %s - %s",
                        self.base_url,
                        resp.status,
                        body[:1000],
                    )
                else:
                    logger.debug(
                        "Nano Banana 2 GET 404 on provider %s",
                        self.base_url,
                    )
                return None
        except Exception as exc:
            logger.warning(
                "Nano Banana 2 GET error on provider %s: %s",
                self.base_url,
                exc,
            )
            return None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


class NanoBanana2Service:
    def __init__(
        self,
        primary_provider: Any,
        fallback_provider: Optional[Any] = None,
    ):
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider

    async def _post(self, endpoint: str, payload: Dict) -> Optional[Dict]:
        response = None
        if hasattr(self.primary_provider, "_post"):
            response = await self.primary_provider._post(endpoint, payload)
        if response is not None:
            return response
        if self.fallback_provider is not None and hasattr(
            self.fallback_provider, "_post"
        ):
            logger.info(
                "Falling back to secondary provider for Nano Banana 2 POST %s",
                endpoint,
            )
            return await self.fallback_provider._post(endpoint, payload)
        return None

    async def _get(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        response = None
        if hasattr(self.primary_provider, "_get"):
            response = await self.primary_provider._get(endpoint, params)
        if response is not None:
            return response
        if self.fallback_provider is not None and hasattr(
            self.fallback_provider, "_get"
        ):
            logger.info(
                "Falling back to secondary provider for Nano Banana 2 GET %s",
                endpoint,
            )
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
        supported_image_urls = image_sources_to_supported_image_urls(
            uploaded_image_urls
        )

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

        logger.info(
            "Nano Banana 2 Kie fallback task: refs=%s aspect_ratio=%s resolution=%s prompt_len=%s model=%s",
            len(normalized_image_input),
            aspect_ratio,
            normalized_resolution,
            len(prompt or ""),
            payload["model"],
        )

        response = await self._post("/api/v1/jobs/createTask", payload)
        if not response or not isinstance(response, dict):
            logger.error("Nano Banana 2 create_task failed, response=%s", response)
            return None
        data = response.get("data")
        if not isinstance(data, dict):
            logger.error(
                "Nano Banana 2 invalid data: %s (full response: %s)",
                data,
                response,
            )
            return None
        task_id = data.get("taskId")
        if not task_id:
            logger.error("No taskId in Nano Banana 2 response: %s", response)
        return task_id

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        response = await self._get(
            "/api/v1/jobs/recordInfo",
            params={"taskId": task_id},
        )
        if not response or not isinstance(response, dict):
            return None
        data = response.get("data")
        if not isinstance(data, dict):
            logger.warning("Nano Banana 2 status invalid data: %s", data)
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
                prompt,
                aspect_ratio,
                resolution,
                image_input,
                output_format,
            )
            if result is not None:
                if isinstance(result, (bytes, bytearray)):
                    return {"image_bytes": bytes(result)}
                return result
            logger.info(
                "Nano Banana 2 APIYI primary failed; trying Kie queued fallback"
            )

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

    async def wait_for_completion(
        self,
        task_id: str,
        max_attempts: int = 60,
        delay: float = 5.0,
    ) -> Optional[Dict]:
        consecutive_failures = 0
        for _attempt in range(max_attempts):
            status = await self.get_task_status(task_id)
            if status is None:
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    logger.error(
                        "Task %s unavailable after %s consecutive errors",
                        task_id,
                        consecutive_failures,
                    )
                    return None
                await asyncio.sleep(delay)
                continue

            consecutive_failures = 0
            task_state = str(status.get("state") or "").lower()
            if task_state == "success":
                return status
            if task_state == "fail":
                logger.error(
                    "Task %s failed: %s",
                    task_id,
                    status.get("failMsg", "Unknown"),
                )
                return None
            await asyncio.sleep(delay)

        logger.warning("Task %s timed out after %s attempts", task_id, max_attempts)
        return None

    async def close(self) -> None:
        if hasattr(self.primary_provider, "close"):
            await self.primary_provider.close()
        if self.fallback_provider is not None and hasattr(
            self.fallback_provider, "close"
        ):
            await self.fallback_provider.close()


class NanoBanana2GeminiProvider:
    """APIYI Gemini-compatible primary provider for Nano Banana 2."""

    MODEL = "gemini-3.1-flash-image-preview"

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=120)
            )
        return self._session

    async def _reference_part(
        self,
        session: aiohttp.ClientSession,
        source: str,
        index: int,
    ) -> Optional[Dict[str, Any]]:
        if source.startswith("data:image/"):
            try:
                header, encoded = source.split(",", 1)
                mime_type = header.replace("data:", "").split(";", 1)[0]
                raw_size = len(base64.b64decode(encoded, validate=False))
                logger.info(
                    "Nano Banana 2 APIYI reference ready: index=%s bytes=%s mime=%s transport=data_uri",
                    index,
                    raw_size,
                    mime_type,
                )
                return {
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": encoded,
                    }
                }
            except Exception:
                logger.exception(
                    "Nano Banana 2 APIYI failed to parse data URI reference index=%s",
                    index,
                )
                return None

        if not source.startswith(("http://", "https://")):
            logger.warning(
                "Nano Banana 2 APIYI unsupported reference source index=%s",
                index,
            )
            return None

        try:
            async with session.get(
                source,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as image_response:
                if image_response.status != 200:
                    logger.warning(
                        "Nano Banana 2 APIYI reference download failed: index=%s status=%s",
                        index,
                        image_response.status,
                    )
                    return None
                image_data = await image_response.read()
                if not image_data:
                    logger.warning(
                        "Nano Banana 2 APIYI reference is empty: index=%s",
                        index,
                    )
                    return None
                mime_type = image_response.content_type or "image/jpeg"
                encoded = base64.b64encode(image_data).decode("ascii")
                logger.info(
                    "Nano Banana 2 APIYI reference ready: index=%s bytes=%s mime=%s transport=url",
                    index,
                    len(image_data),
                    mime_type,
                )
                return {
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": encoded,
                    }
                }
        except Exception:
            logger.exception(
                "Nano Banana 2 APIYI failed to download reference index=%s",
                index,
            )
            return None

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

        provider_prompt, stripped_legacy_wrapper = _normalize_apiyi_prompt(prompt)
        parts: List[Dict[str, Any]] = [{"text": provider_prompt}]

        requested_references = [
            source
            for source in (image_input or [])[:MAX_IMAGE_INPUTS]
            if isinstance(source, str) and source.strip()
        ]
        loaded_references = 0
        for index, source in enumerate(requested_references, start=1):
            part = await self._reference_part(session, source.strip(), index)
            if part is None:
                # The first image carries identity. Continuing without it produces a
                # different person while looking like a successful edit, so fail over.
                if index == 1:
                    logger.error(
                        "Nano Banana 2 APIYI primary reference unavailable; aborting primary request"
                    )
                    return None
                logger.warning(
                    "Nano Banana 2 APIYI skipped unavailable extra reference index=%s",
                    index,
                )
                continue
            parts.append(part)
            loaded_references += 1

        if requested_references and loaded_references == 0:
            logger.error(
                "Nano Banana 2 APIYI received references but loaded none; aborting primary request"
            )
            return None

        normalized_resolution = _normalize_resolution(resolution)
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {
                    "aspectRatio": aspect_ratio,
                    "imageSize": normalized_resolution,
                },
            },
        }
        url = f"{self.base_url}/models/{self.MODEL}:generateContent"

        logger.info(
            "Nano Banana 2 APIYI request: model=%s refs=%s/%s aspect_ratio=%s resolution=%s output_format=%s prompt_len=%s legacy_wrapper_stripped=%s",
            self.MODEL,
            loaded_references,
            len(requested_references),
            aspect_ratio,
            normalized_resolution,
            output_format,
            len(provider_prompt),
            stripped_legacy_wrapper,
        )

        try:
            async with session.post(url, headers=headers, json=payload) as response:
                body = await response.text()
                if response.status != 200:
                    logger.warning(
                        "Nano Banana 2 APIYI POST failed: status=%s body=%s",
                        response.status,
                        body[:1000],
                    )
                    return None
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    logger.warning("Nano Banana 2 APIYI response is not JSON")
                    return None

                extracted = _extract_inline_image(data)
                if extracted is None:
                    logger.warning(
                        "Nano Banana 2 APIYI response contains no inline image"
                    )
                    return None
                image_bytes, mime_type = extracted
                logger.info(
                    "Nano Banana 2 APIYI image ready: bytes=%s resolution=%s mime=%s",
                    len(image_bytes),
                    normalized_resolution,
                    mime_type,
                )
                return image_bytes
        except Exception as exc:
            logger.warning("Nano Banana 2 APIYI provider error: %s", exc)
            return None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


# APIYI remains the preferred provider by product decision. Existing environment
# variable names are retained for deployment compatibility.
_kie_provider = ProviderClient(
    api_key=config.KIE_AI_API_KEY or config.NANOBANANA_API_KEY,
    base_url="https://api.kie.ai",
)

_apiyi_provider = None
if config.NANOBANANA2_FALLBACK_API_KEY and config.NANOBANANA2_FALLBACK_BASE_URL:
    _apiyi_provider = NanoBanana2GeminiProvider(
        api_key=config.NANOBANANA2_FALLBACK_API_KEY,
        base_url=config.NANOBANANA2_FALLBACK_BASE_URL,
    )

if _apiyi_provider:
    logger.info(
        "Nano Banana 2: using APIYI Gemini-compatible provider as primary, Kie.ai as fallback"
    )
    nano_banana_2_service = NanoBanana2Service(
        primary_provider=_apiyi_provider,
        fallback_provider=_kie_provider,
    )
else:
    logger.info("Nano Banana 2: APIYI is not configured; using Kie.ai")
    nano_banana_2_service = NanoBanana2Service(
        primary_provider=_kie_provider,
        fallback_provider=None,
    )
