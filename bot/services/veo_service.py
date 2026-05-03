"""Veo 3.1 Video Generation Service via Kie.ai API"""

import logging
from typing import Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

_MODEL_NAMES = {
    "veo3_fast": "veo3_fast",
    "veo3": "veo3",
    "veo3_lite": "veo3_lite",
}


class VeoService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.kie.ai"
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
                f"{self.base_url}{endpoint}", headers=headers, json=payload
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                error = await resp.text()
                logger.error(f"Veo POST {endpoint} failed: {resp.status} - {error}")
                return None
        except Exception as e:
            logger.exception(f"Veo POST error: {e}")
            return None

    async def generate_video(
        self,
        prompt: str,
        model: str = "veo3_fast",
        aspect_ratio: str = "16:9",
        resolution: str = "720p",
        image_urls: Optional[List[str]] = None,
        callback_url: Optional[str] = None,
    ) -> Optional[Dict]:
        """Generate video with Veo 3.1. Returns {'task_id': ...} on success."""
        api_model = _MODEL_NAMES.get(model, "veo3_fast")

        payload: Dict = {
            "prompt": prompt,
            "model": api_model,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "enableTranslation": True,
        }

        # Only veo3_fast supports image reference input
        if image_urls and api_model == "veo3_fast":
            payload["imageUrls"] = image_urls
            payload["generationType"] = "REFERENCE_2_VIDEO"
        else:
            payload["generationType"] = "TEXT_2_VIDEO"

        if callback_url:
            payload["callBackUrl"] = callback_url

        resp = await self._post("/api/v1/veo/generate", payload)
        if not resp:
            return None
        if resp.get("code") == 200:
            task_id = resp.get("data", {}).get("taskId")
            if task_id:
                return {"task_id": task_id}
        logger.error(f"Veo generate failed: {resp}")
        return None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


from bot.config import config

veo_service = VeoService(api_key=config.KIE_AI_API_KEY)
