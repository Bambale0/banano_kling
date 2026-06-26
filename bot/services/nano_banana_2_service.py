import logging
from typing import Dict, List, Optional

import aiohttp

from bot.services.media_input_utils import (
    image_sources_to_data_uris,
    image_sources_to_supported_image_urls,
    is_local_upload_source,
)
from bot.services.kie_file_upload_service import kie_file_upload_service

logger = logging.getLogger(__name__)
MAX_IMAGE_INPUTS = 8
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
    def __init__(self, primary_provider: ProviderClient, fallback_provider: Optional[ProviderClient] = None):
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider

    async def _post(self, endpoint: str, payload: Dict) -> Optional[Dict]:
        resp = await self.primary_provider._post(endpoint, payload)
        if resp is not None:
            return resp
        if self.fallback_provider is not None:
            logger.info("Falling back to secondary provider for Nano Banana 2 POST %s", endpoint)
            return await self.fallback_provider._post(endpoint, payload)
        return None

    async def _get(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        resp = await self.primary_provider._get(endpoint, params)
        if resp is not None:
            return resp
        if self.fallback_provider is not None:
            logger.info("Falling back to secondary provider for Nano Banana 2 GET %s", endpoint)
            return await self.fallback_provider._get(endpoint, params)
        return None

    async def create_task(
        self,
        prompt: str,
        image_input: List[str] = None,
        aspect_ratio: str = "auto",
        resolution: str = "4K",
        output_format: str = "png",
        callback_url: str = None,
    ) -> Optional[str]:
        supported_image_urls = image_sources_to_supported_image_urls(image_input)
        uploaded_image_urls = await kie_file_upload_service.upload_local_image_sources(
            supported_image_urls
        )
        normalized_image_input = [
            source
            for source in uploaded_image_urls
            if isinstance(source, str) and source
        ]
        if len(normalized_image_input) > MAX_IMAGE_INPUTS:
            logger.warning(
                "Nano Banana 2 create_task collapsing references from %s to %s for identity safety",
                len(normalized_image_input),
                MAX_IMAGE_INPUTS,
            )
            normalized_image_input = normalized_image_input[:MAX_IMAGE_INPUTS]

        if not normalized_image_input and image_input:
            fallback_inputs = [
                source
                for source in image_input
                if not (isinstance(source, str) and is_local_upload_source(source))
            ]
            if not fallback_inputs:
                logger.error("Nano Banana 2 create_task aborted: all local reference files are missing")
                return None
            # Предпочитаем URL-ы из локального upload flow, но сохраняем fallback,
            # чтобы не ломать нестандартные источники изображений.
            normalized_image_input = image_sources_to_data_uris(fallback_inputs)

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
    ) -> Optional[Dict]:

        task_id = await self.create_task(
            prompt, image_input, aspect_ratio, resolution, output_format, callback_url
        )
        if task_id:
            return {"task_id": task_id}
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

_primary = ProviderClient(
    api_key=config.KIE_AI_API_KEY or config.NANOBANANA_API_KEY,
    base_url="https://api.kie.ai",
)
_fallback = None
if config.NANOBANANA2_FALLBACK_API_KEY and config.NANOBANANA2_FALLBACK_BASE_URL:
    _fallback = ProviderClient(
        api_key=config.NANOBANANA2_FALLBACK_API_KEY,
        base_url=config.NANOBANANA2_FALLBACK_BASE_URL,
    )

nano_banana_2_service = NanoBanana2Service(
    primary_provider=_primary,
    fallback_provider=_fallback,
)
