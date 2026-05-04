"""Hailuo Video Generation Service via Kie.ai API"""

import logging
from typing import Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)

# Maps internal model keys → Kie.ai model identifiers
HAILUO_API_MODELS = {
    # Hailuo 2.3 (image-to-video only)
    "hailuo_23_pro": "hailuo/2-3-image-to-video-pro",
    "hailuo_23_std": "hailuo/2-3-image-to-video-standard",
    # Hailuo 02 (text-to-video, optional image)
    "hailuo_pro": "hailuo/02-text-to-video-pro",
    "hailuo_std": "hailuo/02-text-to-video-standard",
    # Hailuo 02 image-to-video
    "hailuo_i2v_pro": "hailuo/02-image-to-video-pro",
    "hailuo_i2v_std": "hailuo/02-image-to-video-standard",
}

# Models that REQUIRE an image_url
HAILUO_IMAGE_REQUIRED = {
    "hailuo_23_pro",
    "hailuo_23_std",
    "hailuo_i2v_pro",
    "hailuo_i2v_std",
}

# Models that support resolution selection (768P / 1080P)
HAILUO_HAS_RESOLUTION = {"hailuo_23_pro", "hailuo_23_std", "hailuo_i2v_std"}

# Models that support duration selection (6 / 10 sec)
HAILUO_HAS_DURATION = {"hailuo_23_pro", "hailuo_23_std", "hailuo_std", "hailuo_i2v_std"}

# Allowed duration values per model — snap to nearest if user sends e.g. 5
HAILUO_ALLOWED_DURATIONS: Dict[str, list] = {
    "hailuo_23_pro": [6, 10],
    "hailuo_23_std": [6, 10],
    "hailuo_std": [6, 10],
    "hailuo_i2v_std": [6, 10],
}


class HailuoService:
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
                logger.error(f"Hailuo POST {endpoint} failed: {resp.status} - {error}")
                return None
        except Exception as e:
            logger.exception(f"Hailuo POST error: {e}")
            return None

    async def generate_video(
        self,
        model_key: str,
        prompt: str,
        image_url: Optional[str] = None,
        end_image_url: Optional[str] = None,
        duration: int = 6,
        resolution: str = "768P",
        nsfw_checker: bool = False,
        prompt_optimizer: bool = False,
        callback_url: Optional[str] = None,
    ) -> Optional[Dict]:
        """Generate video using Hailuo. Returns {'task_id': ...} on success."""
        api_model = HAILUO_API_MODELS.get(model_key)
        if not api_model:
            logger.error(f"Unknown Hailuo model key: {model_key}")
            return None

        input_data: Dict = {
            "prompt": prompt,
            "nsfw_checker": nsfw_checker,
        }

        if model_key in HAILUO_HAS_DURATION:
            allowed = HAILUO_ALLOWED_DURATIONS.get(model_key, [6, 10])
            snapped = min(allowed, key=lambda x: abs(x - duration))
            input_data["duration"] = str(snapped)

        if model_key in HAILUO_HAS_RESOLUTION:
            # 1080p is not supported for 10s videos on 2.3 models
            effective_resolution = resolution
            if duration >= 10 and resolution == "1080P":
                effective_resolution = "768P"
            input_data["resolution"] = effective_resolution

        if model_key in (
            "hailuo_pro",
            "hailuo_std",
            "hailuo_i2v_pro",
            "hailuo_i2v_std",
        ):
            input_data["prompt_optimizer"] = prompt_optimizer

        if image_url:
            input_data["image_url"] = image_url

        if end_image_url and model_key in ("hailuo_i2v_pro", "hailuo_i2v_std"):
            input_data["end_image_url"] = end_image_url

        payload: Dict = {
            "model": api_model,
            "input": input_data,
        }
        if callback_url:
            payload["callBackUrl"] = callback_url

        resp = await self._post("/api/v1/jobs/createTask", payload)
        if not resp:
            return None
        if resp.get("code") == 200:
            task_id = resp.get("data", {}).get("taskId")
            if task_id:
                return {"task_id": task_id}
        logger.error(f"Hailuo generate failed: {resp}")
        return None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


from bot.config import config

hailuo_service = HailuoService(api_key=config.KIE_AI_API_KEY)
