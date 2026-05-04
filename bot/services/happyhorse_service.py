"""HappyHorse video generation service via Kie.ai Market API."""

import asyncio
import json
import logging
from typing import Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


HAPPYHORSE_API_MODELS = {
    "happyhorse_t2v": "happyhorse/text-to-video",
    "happyhorse_i2v": "happyhorse/image-to-video",
    "happyhorse_ref2v": "happyhorse/reference-to-video",
    "happyhorse_edit": "happyhorse/video-edit",
}

HAPPYHORSE_IMAGE_REQUIRED = {"happyhorse_i2v", "happyhorse_ref2v"}
HAPPYHORSE_VIDEO_REQUIRED = {"happyhorse_edit"}


class HappyHorseService:
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
                text = await resp.text()
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    logger.error(
                        "HappyHorse POST %s returned invalid JSON: %s",
                        endpoint,
                        text[:500],
                    )
                    return None
                if resp.status == 200:
                    return data
                logger.error(
                    "HappyHorse POST %s failed: %s - %s",
                    endpoint,
                    resp.status,
                    text[:1000],
                )
                return data
        except Exception as e:
            logger.exception(f"HappyHorse POST error: {e}")
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
                error = await resp.text()
                logger.error(
                    "HappyHorse GET %s failed: %s - %s",
                    endpoint,
                    resp.status,
                    error[:1000],
                )
                return None
        except Exception as e:
            logger.exception(f"HappyHorse GET error: {e}")
            return None

    async def generate_video(
        self,
        model_key: str,
        prompt: str,
        image_urls: Optional[List[str]] = None,
        video_url: Optional[str] = None,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        resolution: str = "1080p",
        audio_setting: str = "auto",
        seed: Optional[int] = None,
        callback_url: Optional[str] = None,
    ) -> Optional[Dict]:
        """Create a HappyHorse task. Returns {'task_id': ...} on success."""
        api_model = HAPPYHORSE_API_MODELS.get(model_key)
        if not api_model:
            logger.error(f"Unknown HappyHorse model key: {model_key}")
            return None

        image_urls = [url for url in (image_urls or []) if url]
        input_data: Dict = {
            "prompt": prompt,
            "resolution": resolution,
        }

        if model_key == "happyhorse_t2v":
            input_data.update(
                {
                    "aspect_ratio": aspect_ratio,
                    "duration": int(duration),
                }
            )
        elif model_key == "happyhorse_i2v":
            if not image_urls:
                logger.error("HappyHorse image-to-video requires image_urls")
                return None
            input_data.update(
                {
                    "image_urls": image_urls[:9],
                    "duration": int(duration),
                }
            )
        elif model_key == "happyhorse_ref2v":
            if not image_urls:
                logger.error("HappyHorse reference-to-video requires reference_image")
                return None
            input_data.update(
                {
                    "reference_image": image_urls[:9],
                    "aspect_ratio": aspect_ratio,
                    "duration": int(duration),
                }
            )
        elif model_key == "happyhorse_edit":
            if not video_url:
                logger.error("HappyHorse video-edit requires video_url")
                return None
            input_data.update(
                {
                    "video_url": video_url,
                    "audio_setting": audio_setting,
                }
            )
            if image_urls:
                input_data["reference_image"] = image_urls[:5]

        if seed is not None:
            input_data["seed"] = seed

        payload: Dict = {"model": api_model, "input": input_data}
        if callback_url:
            payload["callBackUrl"] = callback_url

        resp = await self._post("/api/v1/jobs/createTask", payload)
        if resp and resp.get("code") == 200:
            task_id = resp.get("data", {}).get("taskId")
            if task_id:
                return {"task_id": task_id}
        logger.error(f"HappyHorse generate failed: {resp}")
        return None

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        """Query task status using the unified Market recordInfo endpoint."""
        resp = await self._get("/api/v1/jobs/recordInfo", params={"taskId": task_id})
        if not resp or not isinstance(resp, dict):
            return None

        data = resp.get("data")
        if not isinstance(data, dict):
            logger.warning(f"HappyHorse status invalid data: {data}")
            return None

        state = str(data.get("state", "unknown")).lower()
        result_json_str = data.get("resultJson", "{}")
        try:
            result_json = json.loads(result_json_str) if result_json_str else {}
            result_urls = result_json.get("resultUrls", [])
            output = result_urls[0] if result_urls else None
        except (json.JSONDecodeError, KeyError, TypeError):
            output = None

        return {
            "data": {
                "task_id": task_id,
                "status": state,
                "output": output,
                "fail_code": data.get("failCode"),
                "fail_msg": data.get("failMsg"),
            },
            "raw": data,
        }

    async def wait_for_completion(
        self, task_id: str, max_attempts: int = 90, delay: float = 5.0
    ) -> Optional[Dict]:
        consecutive_failures = 0
        for attempt in range(max_attempts):
            status = await self.get_task_status(task_id)
            if status is None:
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    logger.error(
                        "HappyHorse task %s unavailable after %s status checks",
                        task_id,
                        consecutive_failures,
                    )
                    return None
                await asyncio.sleep(delay)
                continue

            consecutive_failures = 0
            task_status = status.get("data", {}).get("status", "").lower()
            if task_status in {"success", "completed", "succeeded"}:
                return status
            if task_status in {"fail", "failed", "error"}:
                logger.error(f"HappyHorse task {task_id} failed")
                return status
            logger.debug(
                "HappyHorse task %s: %s, attempt %s",
                task_id,
                task_status,
                attempt + 1,
            )
            await asyncio.sleep(delay)

        logger.warning(f"HappyHorse task {task_id} timeout")
        return None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


from bot.config import config

happyhorse_service = HappyHorseService(api_key=config.KIE_AI_API_KEY)
