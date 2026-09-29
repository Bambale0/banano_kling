"""KIE Gemini 3.1 Pro native photo/video analysis adapter."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

import aiohttp

from bot.config import config
from bot.database import get_bot_setting

logger = logging.getLogger(__name__)
MEDIA_ANALYSIS_PROVIDERS = frozenset({"kie_gemini31", "qwen38"})


async def media_analysis_provider() -> str:
    value = await get_bot_setting("media_analysis_provider", "kie_gemini31")
    if value not in MEDIA_ANALYSIS_PROVIDERS:
        raise ValueError("Invalid media_analysis_provider setting")
    return value


class KieGemini31Service:
    MODEL = "gemini-3.1-pro"
    ENDPOINT = "/gemini-3.1-pro/v1/chat/completions"

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None):
        self.api_key = config.KIE_AI_API_KEY if api_key is None else api_key
        self.base_url = (config.KIE_BASE_URL if base_url is None else base_url).rstrip("/")

    async def analyze_media(
        self, *, media_url: str, user_instruction: str, system_prompt: str | None = None,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("KIE_AI_API_KEY is not configured for media analysis")
        if not media_url.strip():
            raise ValueError("media_url is required")
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": [
            {"type": "text", "text": user_instruction},
            {"type": "image_url", "image_url": {"url": media_url}},
        ]})
        payload = {
            "messages": messages, "stream": False,
            "include_thoughts": False, "reasoning_effort": "high",
        }
        attempts = max(1, min(3, config.KIE_MEDIA_ANALYSIS_MAX_ATTEMPTS))
        timeout = aiohttp.ClientTimeout(total=max(1, min(300, config.KIE_MEDIA_ANALYSIS_TIMEOUT_SECONDS)))
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in range(1, attempts + 1):
                try:
                    async with session.post(
                        self.base_url + self.ENDPOINT,
                        headers={"Authorization": f"Bearer {self.api_key}"}, json=payload,
                    ) as response:
                        logger.info(
                            "media_analysis provider=kie model=%s request_id=%s attempt=%s status=%s elapsed_ms=%s",
                            self.MODEL, request_id, attempt, response.status,
                            int((time.monotonic() - started) * 1000),
                        )
                        if (response.status == 429 or response.status >= 500) and attempt < attempts:
                            await asyncio.sleep(2 ** (attempt - 1))
                            continue
                        if response.status >= 400:
                            raise RuntimeError(f"KIE Gemini 3.1 Pro: HTTP {response.status} (request_id={request_id})")
                        try:
                            data = await response.json(content_type=None)
                            content = data["choices"][0]["message"]["content"]
                        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                            raise RuntimeError("KIE Gemini 3.1 Pro returned an invalid response") from exc
                        if not isinstance(content, str) or not content.strip():
                            raise RuntimeError("KIE Gemini 3.1 Pro returned empty content")
                        return content.strip()
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    logger.warning(
                        "media_analysis provider=kie model=%s request_id=%s attempt=%s error=%s",
                        self.MODEL, request_id, attempt, type(exc).__name__,
                    )
                    if attempt == attempts:
                        raise RuntimeError(f"KIE Gemini 3.1 Pro network failure (request_id={request_id})") from exc
                    await asyncio.sleep(2 ** (attempt - 1))
        raise RuntimeError("KIE Gemini 3.1 Pro exhausted attempts")
