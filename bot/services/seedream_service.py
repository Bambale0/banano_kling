import logging
from typing import Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


class SeedreamLiteService:
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
                        f"Seedream Lite POST {endpoint} failed: {resp.status} - {error}"
                    )
                    return None
        except Exception as e:
            logger.exception(f"Seedream Lite POST error: {e}")
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
                    logger.error(
                        f"Seedream Lite GET {endpoint} failed: {resp.status} - {error}"
                    )
                    return None
        except Exception as e:
            logger.exception(f"Seedream Lite GET error: {e}")
            return None

    async def create_task(
        self,
        model: str,
        prompt: str,
        image_urls: List[str] = None,
        aspect_ratio: str = "1:1",
        quality: str = "basic",
        nsfw_checker: bool = False,
        callback_url: str = None,
    ) -> Optional[str]:
        payload = {
            "model": model,
            "input": {
                "prompt": prompt,
                "image_urls": image_urls or [],
                "aspect_ratio": aspect_ratio,
                "quality": quality,
                "nsfw_checker": nsfw_checker,
            },
        }
        if callback_url:
            payload["callBackUrl"] = callback_url

        resp = await self._post("/api/v1/jobs/createTask", payload)
        if not resp or not isinstance(resp, dict):
            logger.error(f"Seedream Lite create_task failed, resp: {resp}")
            return None
        data = resp.get("data")
        if not isinstance(data, dict):
            logger.error(f"Seedream Lite invalid data: {data} (full resp: {resp})")
            return None
        task_id = data.get("taskId")
        if not task_id:
            logger.error(f"No taskId in response: {resp}")
        return task_id

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        resp = await self._get(f"/api/v1/jobs/{task_id}")
        if not resp or not isinstance(resp, dict):
            return None
        data = resp.get("data")
        if not isinstance(data, dict):
            logger.warning(f"Seedream Lite status invalid data: {data}")
            return None
        return data

    async def generate_image(
        self,
        prompt: str,
        model: str = "seedream/5-lite-image-to-image",
        image_urls: List[str] = None,
        aspect_ratio: str = "1:1",
        quality: str = "basic",
        nsfw_checker: bool = False,
        callback_url: str = None,
    ) -> Optional[Dict]:
        task_id = await self.create_task(
            model, prompt, image_urls, aspect_ratio, quality, nsfw_checker, callback_url
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

seedream_lite_service = SeedreamLiteService(api_key=config.KIE_AI_API_KEY)
