import asyncio
import json
import logging
from typing import Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)


class AlephService:
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
                        f"Aleph POST {endpoint} failed: {resp.status} - {error}"
                    )
                    return None
        except Exception as e:
            logger.exception(f"Aleph POST error: {e}")
            return None

    async def generate_video(
        self,
        prompt: str,
        video_url: Optional[str],
        duration: int = 5,
        aspect_ratio: str = "16:9",
        callback_url: Optional[str] = None,
        watermark: str = "",
        seed: int = None,
        reference_image: str = None,
    ) -> Optional[Dict]:
        if not video_url:
            logger.error("Aleph requires videoUrl")
            return None

        payload = {
            "prompt": prompt,
            "videoUrl": video_url,
        }
        if callback_url:
            payload["callBackUrl"] = callback_url
        if aspect_ratio:
            payload["aspectRatio"] = aspect_ratio
        if watermark:
            payload["waterMark"] = watermark
        if seed:
            payload["seed"] = seed
        if reference_image:
            payload["referenceImage"] = reference_image
        # uploadCn default false

        resp = await self._post("/api/v1/aleph/generate", payload)
        if resp and resp.get("code") == 200:
            data = resp.get("data", {})
            task_id = data.get("taskId")
            if task_id:
                return {"task_id": task_id}
        logger.error(f"Aleph generate failed: {resp}")
        return None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


from bot.config import config

aleph_service = AlephService(api_key=config.KIE_AI_API_KEY)
