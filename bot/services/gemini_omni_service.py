"""Gemini Omni service via Kie.ai Market API."""

import logging
from typing import Dict, List, Optional

import aiohttp

from bot.services.kling_service import normalize_kie_image_url

logger = logging.getLogger(__name__)

GEMINI_OMNI_MAX_IMAGES = 7
GEMINI_OMNI_MAX_VIDEOS = 1
GEMINI_OMNI_MAX_AUDIO_IDS = 3
GEMINI_OMNI_MAX_CHARACTER_IDS = 3
GEMINI_OMNI_MAX_INPUT_UNITS = 7

GEMINI_OMNI_BASE_VOICES = {
    "achernar",
    "achird",
    "algenib",
    "algieba",
    "alnilam",
    "aoede",
    "autonoe",
    "callirrhoe",
    "charon",
    "despina",
    "enceladus",
    "erinome",
    "fenrir",
    "gacrux",
    "iapetus",
    "kore",
    "laomedeia",
    "leda",
    "orus",
    "puck",
    "pulcherrima",
    "rasalgethi",
    "sadachbia",
    "sadaltager",
    "schedar",
    "sulafat",
    "umbriel",
    "vindemiatrix",
    "zephyr",
    "zubenelgenubi",
}


class GeminiOmniService:
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

    async def _request(self, method: str, endpoint: str, **kwargs) -> Optional[Dict]:
        session = await self._get_session()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with session.request(
                method,
                f"{self.base_url}{endpoint}",
                headers=headers,
                **kwargs,
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status == 200:
                    return data
                logger.error(
                    "Gemini Omni %s %s failed: %s - %s",
                    method,
                    endpoint,
                    resp.status,
                    data,
                )
                return None
        except Exception:
            logger.exception("Gemini Omni %s %s error", method, endpoint)
            return None

    async def generate_video(
        self,
        prompt: str,
        image_urls: Optional[List[str]] = None,
        video_urls: Optional[List[str]] = None,
        audio_ids: Optional[List[str]] = None,
        character_ids: Optional[List[str]] = None,
        duration: int = 4,
        aspect_ratio: str = "16:9",
        resolution: str = "720p",
        seed: Optional[int] = None,
        callback_url: Optional[str] = None,
    ) -> Optional[Dict]:
        image_urls = image_urls or []
        video_urls = video_urls or []
        audio_ids = audio_ids or []
        character_ids = character_ids or []

        if len(video_urls) > GEMINI_OMNI_MAX_VIDEOS:
            return {
                "error": f"Gemini Omni supports maximum {GEMINI_OMNI_MAX_VIDEOS} video reference",
                "code": "too_many_videos",
            }

        image_count = min(len(image_urls), GEMINI_OMNI_MAX_IMAGES)
        video_count = min(len(video_urls), GEMINI_OMNI_MAX_VIDEOS)
        character_count = min(len(character_ids), GEMINI_OMNI_MAX_CHARACTER_IDS)
        quota_used = image_count + video_count * 2 + character_count
        if quota_used > GEMINI_OMNI_MAX_INPUT_UNITS:
            return {
                "error": (
                    "Gemini Omni input quota exceeded: "
                    f"images({image_count}) + videos({video_count})*2 + "
                    f"characters({character_count}) = {quota_used}, "
                    f"max {GEMINI_OMNI_MAX_INPUT_UNITS}"
                ),
                "code": "input_quota_exceeded",
            }

        input_data: Dict = {
            "prompt": prompt,
            "duration": str(duration),
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
        }
        if image_urls:
            input_data["image_urls"] = [
                normalize_kie_image_url(u) for u in image_urls[:GEMINI_OMNI_MAX_IMAGES]
            ]
        if video_urls:
            input_data["video_list"] = [
                {"url": url, "start": 0, "ends": 10}
                for url in video_urls
            ]
        if audio_ids:
            input_data["audio_ids"] = audio_ids[:GEMINI_OMNI_MAX_AUDIO_IDS]
        if character_ids:
            input_data["character_ids"] = character_ids[:GEMINI_OMNI_MAX_CHARACTER_IDS]
        if seed is not None:
            input_data["seed"] = seed

        payload: Dict = {"model": "gemini-omni-video", "input": input_data}
        if callback_url:
            payload["callBackUrl"] = callback_url

        logger.info(
            "Gemini Omni video request: images=%s videos=%s audio_ids=%s character_ids=%s duration=%s ratio=%s resolution=%s",
            len(input_data.get("image_urls", [])),
            len(input_data.get("video_list", [])),
            input_data.get("audio_ids", []),
            input_data.get("character_ids", []),
            input_data.get("duration"),
            input_data.get("aspect_ratio"),
            input_data.get("resolution"),
        )
        resp = await self._request("POST", "/api/v1/jobs/createTask", json=payload)
        if resp and resp.get("code") == 200:
            task_id = resp.get("data", {}).get("taskId")
            if task_id:
                return {"task_id": task_id}
        if resp:
            return {
                "error": resp.get("msg") or "Gemini Omni video task was rejected",
                "code": resp.get("code"),
            }
        logger.error("Gemini Omni video generate failed: %s", resp)
        return None

    async def create_audio(
        self,
        audio_id: str,
        name: str,
        voice_description: str = "",
        example_dialogue: str = "",
    ) -> Optional[Dict]:
        payload = {
            "audio_id": audio_id,
            "name": name,
            "voice_description": voice_description,
            "example_dialogue": example_dialogue,
        }
        resp = await self._request("POST", "/api/v1/omni/audio/create", json=payload)
        if resp and resp.get("code") in (0, 200):
            data = resp.get("data", {})
            audio = data.get("kieAudioId") or data.get("audioId")
            if audio:
                logger.info(
                    "Gemini Omni audio created: base_audio=%s audio_id=%s name=%s",
                    audio_id,
                    audio,
                    data.get("name") or name,
                )
                return {"audio_id": audio, "name": data.get("name") or name}
        logger.error("Gemini Omni audio create failed: %s", resp)
        return None

    async def create_character(
        self,
        description: str,
        image_url: str,
        character_name: str = "",
        audio_ids: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        payload: Dict = {
            "descriptions": description,
            "image_urls": [normalize_kie_image_url(image_url)],
            "character_name": character_name,
        }
        # Older Kie examples used `description`; current OpenAPI marks
        # `descriptions` as required. Sending both keeps compatibility.
        payload["description"] = description
        if audio_ids:
            payload["audio_ids"] = audio_ids[:GEMINI_OMNI_MAX_AUDIO_IDS]
        resp = await self._request(
            "POST", "/api/v1/omni/character/create", json=payload
        )
        if resp and resp.get("code") == 200:
            data = resp.get("data", {})
            character_id = data.get("characterId")
            if character_id:
                return {
                    "character_id": character_id,
                    "name": data.get("characterName") or character_name,
                    "image_url": data.get("imageUrl"),
                }
        logger.error("Gemini Omni character create failed: %s", resp)
        return None

    async def get_task(self, task_id: str) -> Optional[Dict]:
        return await self._request(
            "GET", f"/api/v1/jobs/recordInfo?taskId={task_id}"
        )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


from bot.config import config

gemini_omni_service = GeminiOmniService(api_key=config.KIE_AI_API_KEY)
