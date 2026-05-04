import logging
from typing import Dict, List, Optional

import aiohttp

from bot.services.media_input_utils import (
    image_sources_to_data_uris,
    image_sources_to_supported_image_urls,
)

logger = logging.getLogger(__name__)


def _is_remote_image_reference(source) -> bool:
    return isinstance(source, str) and source.startswith(("http://", "https://"))


class NanoBananaProService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.kie.ai"
        self._session = None

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
                    logger.error(
                        f"Nano Banana Pro POST {endpoint} failed: {resp.status} - {error}"
                    )
                    return None
        except Exception as e:
            logger.exception(f"Nano Banana Pro POST error: {e}")
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
                            f"Nano Banana Pro GET {endpoint} failed: {resp.status} - {error}"
                        )
                    else:
                        logger.debug(
                            f"Nano Banana Pro GET {endpoint} 404 (expected for non-existent task)"
                        )
                    return None
        except Exception as e:
            logger.exception(f"Nano Banana Pro GET error: {e}")
            return None

    async def create_task(
        self,
        prompt: str,
        image_input: List[str] = None,
        aspect_ratio: str = "1:1",
        resolution: str = "4K",
        output_format: str = "png",
        callback_url: str = None,
    ) -> Optional[str]:
        fallback_image_urls = image_sources_to_supported_image_urls(image_input)
        normalized_image_input = image_sources_to_data_uris(image_input)
        use_image_urls = bool(fallback_image_urls) and all(
            _is_remote_image_reference(source) for source in fallback_image_urls
        )
        if use_image_urls and fallback_image_urls:
            payload = {
                "model": "google/nano-banana-edit",
                "input": {
                    "prompt": prompt,
                    "image_urls": fallback_image_urls,
                    "output_format": output_format,
                    "image_size": aspect_ratio,
                },
            }
        else:
            payload = {
                "model": "nano-banana-pro",
                "input": {
                    "prompt": prompt,
                    "aspect_ratio": aspect_ratio,
                    "resolution": resolution,
                    "output_format": output_format,
                },
            }
            if normalized_image_input:
                payload["input"]["image_input"] = normalized_image_input
        if callback_url:
            payload["callBackUrl"] = callback_url

        logger.info(
            "Nano Banana Pro create_task: refs=%s aspect_ratio=%s resolution=%s transport=%s model=%s",
            len(fallback_image_urls or normalized_image_input),
            aspect_ratio,
            resolution,
            "image_urls" if use_image_urls else "image_input",
            payload["model"],
        )

        resp = await self._post("/api/v1/jobs/createTask", payload)
        if not resp or not isinstance(resp, dict):
            logger.error(f"Nano Banana Pro create_task failed, resp: {resp}")
            return None
        data = resp.get("data")
        if not isinstance(data, dict):
            logger.error(f"Nano Banana Pro invalid data: {data} (full resp: {resp})")
            return None
        task_id = data.get("taskId")
        if not task_id:
            logger.error(f"No taskId in response: {resp}")
        return task_id

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        resp = await self._get(
            "/api/v1/common/getTaskDetail", params={"taskId": task_id}
        )
        if not resp or not isinstance(resp, dict):
            return None
        data = resp.get("data")
        if not isinstance(data, dict):
            logger.warning(f"Nano Banana Pro status invalid data: {data}")
            return None
        return data

    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
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
        if self._session and not self._session.closed:
            await self._session.close()


from bot.config import config

nano_banana_pro_service = NanoBananaProService(
    api_key=config.KIE_AI_API_KEY or config.NANOBANANA_API_KEY
)
