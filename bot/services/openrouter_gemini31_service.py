"""OpenRouter Gemini 3.1 Pro fallback for media analysis."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

from bot.config import config

logger = logging.getLogger(__name__)
_RETRYABLE_STATUSES = {408, 409, 425, 429}


def _extract_text(data: Any) -> str:
    if not isinstance(data, dict):
        raise TypeError("OpenRouter Gemini returned a non-object response")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("OpenRouter Gemini returned no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise TypeError("OpenRouter Gemini returned an invalid choice")
    message = first.get("message")
    if not isinstance(message, dict):
        raise TypeError("OpenRouter Gemini returned no message")
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        if parts:
            return "\n".join(parts)
    raise RuntimeError("OpenRouter Gemini returned empty content")


class OpenRouterGemini31Service:
    """Gemini-only fallback transport through OpenRouter."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = (
            config.OPENROUTER_API_KEY if api_key is None else api_key
        ).strip()
        self.base_url = (
            config.OPENROUTER_BASE_URL if base_url is None else base_url
        ).rstrip("/")
        self.model = (
            config.OPENROUTER_GEMINI31_MODEL if model is None else model
        ).strip()
        self.timeout_seconds = max(
            30, int(config.OPENROUTER_GEMINI31_TIMEOUT_SECONDS)
        )
        self.max_attempts = min(
            3, max(1, int(config.OPENROUTER_GEMINI31_MAX_ATTEMPTS))
        )
        self.enabled = bool(self.api_key and self.base_url and self.model)

    async def analyze_media(
        self,
        *,
        media_url: str,
        media_kind: str,
        user_instruction: str,
        system_prompt: str | None = None,
    ) -> str:
        if not self.enabled:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")
        if media_kind not in {"image", "video"}:
            raise ValueError("media_kind must be image or video")

        media_type = "image_url" if media_kind == "image" else "video_url"
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "messages": [],
            "temperature": 0.2,
            "max_tokens": 8192,
            "reasoning": {"effort": "high"},
        }
        if system_prompt:
            payload["messages"].append({"role": "system", "content": system_prompt})
        payload["messages"].append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_instruction},
                    {media_type: {"url": media_url}, "type": media_type},
                ],
            }
        )

        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in range(1, self.max_attempts + 1):
                try:
                    async with session.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    ) as response:
                        raw = await response.text()
                        if (
                            response.status >= 500
                            or response.status in _RETRYABLE_STATUSES
                        ):
                            last_error = RuntimeError(
                                f"OpenRouter Gemini transient HTTP {response.status}"
                            )
                            logger.warning(
                                "media_analysis provider=openrouter_gemini model=%s "
                                "attempt=%s status=%s",
                                self.model,
                                attempt,
                                response.status,
                            )
                            if attempt < self.max_attempts:
                                await asyncio.sleep(2 ** (attempt - 1))
                                continue
                            raise last_error
                        if response.status >= 400:
                            raise RuntimeError(
                                f"OpenRouter Gemini HTTP {response.status}"
                            )
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError as exc:
                            raise RuntimeError(
                                "OpenRouter Gemini returned invalid JSON"
                            ) from exc
                        return _extract_text(data)
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    last_error = exc
                    if attempt < self.max_attempts:
                        await asyncio.sleep(2 ** (attempt - 1))
                        continue
                    raise RuntimeError(
                        "OpenRouter Gemini network failure"
                    ) from exc
        raise RuntimeError(f"OpenRouter Gemini exhausted attempts: {last_error}")


openrouter_gemini31_service = OpenRouterGemini31Service()
