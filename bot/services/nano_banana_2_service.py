import json
import logging
from typing import Dict, List, Optional

import aiohttp

from bot.services.kling_service import normalize_kie_image_url

logger = logging.getLogger(__name__)


class NanoBanana2Service:
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
                error = await resp.text()
                logger.error(
                    "Nano Banana 2 POST %s failed: %s - %s",
                    endpoint,
                    resp.status,
                    error,
                )
                try:
                    payload = json.loads(error)
                    if isinstance(payload, dict):
                        payload.setdefault("code", resp.status)
                        payload["_http_status"] = resp.status
                        return payload
                except (json.JSONDecodeError, TypeError):
                    pass
                return {
                    "code": resp.status,
                    "msg": error,
                    "data": None,
                    "_http_status": resp.status,
                }
        except Exception as e:
            logger.exception(f"Nano Banana 2 POST error: {e}")
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
                            f"Nano Banana 2 GET {endpoint} failed: {resp.status} - {error}"
                        )
                    else:
                        logger.debug(
                            f"Nano Banana 2 GET {endpoint} 404 (expected for non-existent task)"
                        )
                    return None
        except Exception as e:
            logger.exception(f"Nano Banana 2 GET error: {e}")
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
        # Normalize relative URLs to absolute (Kie.ai cannot fetch relative paths)
        normalized_input = [normalize_kie_image_url(url) for url in (image_input or [])]

        def _build_payload(selected_resolution: str) -> Dict:
            return {
                "model": "nano-banana-2",
                "input": {
                    "prompt": prompt,
                    "image_input": normalized_input,
                    "aspect_ratio": aspect_ratio,
                    "resolution": selected_resolution,
                    "output_format": output_format,
                },
            }

        def _retry_resolutions(selected_resolution: str) -> list[str]:
            candidates = [selected_resolution]
            for fallback in ("2K", "1K"):
                if fallback not in candidates:
                    candidates.append(fallback)
            return candidates

        def _is_validation_error(response: Dict) -> bool:
            code = response.get("code") or response.get("_http_status")
            msg = str(response.get("msg") or response.get("message") or "")
            return str(code) == "422" or "validation" in msg.lower()

        last_resp: Optional[Dict] = None
        for selected_resolution in _retry_resolutions(resolution):
            payload = _build_payload(selected_resolution)
            if callback_url:
                payload["callBackUrl"] = callback_url

            resp = await self._post("/api/v1/jobs/createTask", payload)
            last_resp = resp
            if not resp or not isinstance(resp, dict):
                logger.error("Nano Banana 2 create_task failed, resp: %s", resp)
                return None

            if resp.get("code") not in (None, 200):
                logger.error(
                    "Nano Banana 2 create_task rejected: code=%s msg=%s resolution=%s",
                    resp.get("code"),
                    resp.get("msg"),
                    selected_resolution,
                )
                if _is_validation_error(resp) and selected_resolution != "1K":
                    continue
                return None

            data = resp.get("data")
            if not isinstance(data, dict):
                logger.error(
                    "Nano Banana 2 invalid data: %s (full resp: %s)", data, resp
                )
                return None
            task_id = data.get("taskId")
            if not task_id:
                logger.error("No taskId in response: %s", resp)
                return None
            if selected_resolution != resolution:
                logger.info(
                    "Nano Banana 2 task created after fallback resolution %s -> %s",
                    resolution,
                    selected_resolution,
                )
            return task_id

        logger.error("Nano Banana 2 create_task exhausted retries, last_resp: %s", last_resp)
        return None

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        resp = await self._get(
            "/api/v1/jobs/recordInfo", params={"taskId": task_id}
        )
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
        if self._session and not self._session.closed:
            await self._session.close()


from bot.config import config

nano_banana_2_service = NanoBanana2Service(
    api_key=config.KIE_AI_API_KEY or config.NANOBANANA_API_KEY
)
