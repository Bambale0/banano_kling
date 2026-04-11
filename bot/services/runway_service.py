import asyncio
import json
import logging
from typing import Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


class RunwayService:
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
                        f"Runway POST {endpoint} failed: {resp.status} - {error}"
                    )
                    return None
        except Exception as e:
            logger.exception(f"Runway POST error: {e}")
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
                        f"Runway GET {endpoint} failed: {resp.status} - {error}"
                    )
                    return None
        except Exception as e:
            logger.exception(f"Runway GET error: {e}")
            return None

    async def create_task(
        self,
        prompt: str,
        image_url: Optional[str] = None,
        duration: int = 5,
        quality: str = "720p",
        aspect_ratio: Optional[str] = None,
        water_mark: str = "",
        callback_url: Optional[str] = None,
    ) -> Optional[str]:
        payload = {
            "prompt": prompt,
            "duration": duration,
            "quality": quality,
        }
        if image_url:
            payload["imageUrl"] = image_url
        if aspect_ratio:
            payload["aspectRatio"] = aspect_ratio
        if water_mark:
            payload["waterMark"] = water_mark
        if callback_url:
            payload["callBackUrl"] = callback_url

        resp = await self._post("/api/v1/runway/generate", payload)
        if not resp or not isinstance(resp, dict):
            logger.error(f"Runway create_task failed, resp: {resp}")
            return None
        data = resp.get("data")
        if not isinstance(data, dict):
            logger.error(f"Runway invalid data: {data} (full resp: {resp})")
            return None
        task_id = data.get("taskId")
        if not task_id:
            logger.error(f"No taskId in response: {resp}")
        logger.info(f"Runway task created: {task_id}")
        return task_id

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        resp = await self._get(f"/api/v1/jobs/{task_id}")
        if not resp or not isinstance(resp, dict):
            return None
        data = resp.get("data")
        if not isinstance(data, dict):
            logger.warning(f"Runway status invalid data: {data}")
            return None
        # Parse like Kling
        status = data.get("status", "unknown").lower()
        result_json_str = data.get("resultJson", "{}")
        try:
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

    async def generate_video(
        self,
        prompt: str,
        image_url: Optional[str] = None,
        duration: int = 5,
        quality: str = "720p",
        aspect_ratio: Optional[str] = None,
        water_mark: str = "",
        callback_url: Optional[str] = None,
    ) -> Optional[Dict]:
        task_id = await self.create_task(
            prompt, image_url, duration, quality, aspect_ratio, water_mark, callback_url
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
            task_status = status.get("data", {}).get("status", "").lower()
            if task_status in ["completed", "succeeded", "success"]:
                return status
            elif task_status in ["failed", "error", "fail"]:
                logger.error(f"Task {task_id} failed")
                return status
            await asyncio.sleep(delay)
        logger.warning(f"Task {task_id} timeout after {max_attempts} attempts")
        return None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


from bot.config import config

runway_service = RunwayService(api_key=config.KIE_AI_API_KEY)
