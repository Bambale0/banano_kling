"""OpenRouter Qwen 3.8 multimodal adapter for prompt analysis."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

from bot.config import config

logger = logging.getLogger(__name__)

_RETRYABLE_STATUSES = {408, 409, 425, 429}


def _extract_chat_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("Qwen 3.8 вернул ответ без choices")

    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text") or item.get("content")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        if parts:
            return "\n".join(parts)

    raise RuntimeError("Qwen 3.8 вернул пустой текст")


def _provider_error_message(raw_text: str) -> str:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        return raw_text.strip()[:300]

    error = data.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("code")
        if message:
            return str(message)[:300]
    message = data.get("message") or data.get("msg")
    return str(message or "provider error")[:300]


class OpenRouterQwen38Service:
    """Thin OpenAI-compatible client for qwen/qwen3.8-max-0902 on OpenRouter."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else config.OPENROUTER_API_KEY).strip()
        self.base_url = (
            base_url if base_url is not None else config.OPENROUTER_BASE_URL
        ).rstrip("/")
        self.model = (model if model is not None else config.QWEN38_PROMPT_MODEL).strip()
        self.max_tokens = max(256, int(config.QWEN38_PROMPT_MAX_TOKENS))
        self.reasoning_effort = str(config.QWEN38_PROMPT_REASONING_EFFORT or "").strip()
        self.timeout_seconds = max(30, int(config.QWEN38_PROMPT_TIMEOUT_SECONDS))
        self.max_attempts = min(3, max(1, int(config.QWEN38_PROMPT_MAX_ATTEMPTS)))
        self.enabled = bool(self.api_key and self.base_url and self.model)

    @property
    def chat_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _payload(
        self,
        *,
        user_content: list[dict[str, Any]],
        system_prompt: str | None = None,
        json_response: bool = True,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_content})

        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": self.max_tokens,
        }
        if json_response:
            payload["response_format"] = {"type": "json_object"}

        effective_reasoning = (
            self.reasoning_effort
            if reasoning_effort is None
            else str(reasoning_effort).strip()
        )
        if effective_reasoning:
            payload["reasoning"] = {"effort": effective_reasoning}
        return payload

    async def _complete(
        self,
        *,
        user_content: list[dict[str, Any]],
        system_prompt: str | None = None,
        json_response: bool = True,
        reasoning_effort: str | None = None,
    ) -> str:
        if not self.enabled:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._payload(
            user_content=user_content,
            system_prompt=system_prompt,
            json_response=json_response,
            reasoning_effort=reasoning_effort,
        )
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        last_error: Exception | None = None

        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in range(self.max_attempts):
                try:
                    async with session.post(
                        self.chat_url,
                        headers=headers,
                        json=payload,
                    ) as response:
                        raw_text = await response.text()
                        if response.status >= 500 or response.status in _RETRYABLE_STATUSES:
                            last_error = RuntimeError(
                                f"OpenRouter Qwen 3.8 временно недоступен: HTTP {response.status}"
                            )
                            logger.warning(
                                "OpenRouter Qwen 3.8 retryable error: status=%s attempt=%s detail=%s",
                                response.status,
                                attempt + 1,
                                _provider_error_message(raw_text),
                            )
                            if attempt < self.max_attempts - 1:
                                await asyncio.sleep(2**attempt)
                                continue
                            raise last_error
                        if response.status >= 400:
                            detail = _provider_error_message(raw_text)
                            raise RuntimeError(
                                f"OpenRouter Qwen 3.8 ошибка: HTTP {response.status}: {detail}"
                            )

                        try:
                            data = json.loads(raw_text)
                        except json.JSONDecodeError as exc:
                            raise RuntimeError(
                                "OpenRouter Qwen 3.8 вернул некорректный JSON"
                            ) from exc
                        return _extract_chat_text(data)
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    last_error = exc
                    logger.warning(
                        "OpenRouter Qwen 3.8 network error: attempt=%s error=%s",
                        attempt + 1,
                        type(exc).__name__,
                    )
                    if attempt < self.max_attempts - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    raise RuntimeError("OpenRouter Qwen 3.8 недоступен по сети") from exc

        raise RuntimeError(f"OpenRouter Qwen 3.8 не вернул результат: {last_error}")

    async def analyze_image(
        self,
        *,
        image_url: str,
        system_prompt: str,
        user_instruction: str,
    ) -> str:
        image_url = str(image_url or "").strip()
        if not image_url:
            raise ValueError("image_url is required")
        return await self._complete(
            system_prompt=system_prompt,
            user_content=[
                {"type": "text", "text": user_instruction},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        )

    async def analyze_video(
        self,
        *,
        video_url: str,
        user_instruction: str,
        system_prompt: str | None = None,
        json_response: bool = True,
        reasoning_effort: str | None = None,
    ) -> str:
        video_url = str(video_url or "").strip()
        if not video_url:
            raise ValueError("video_url is required")
        return await self._complete(
            user_content=[
                {"type": "text", "text": user_instruction},
                {"type": "video_url", "video_url": {"url": video_url}},
            ],
            system_prompt=system_prompt,
            json_response=json_response,
            reasoning_effort=reasoning_effort,
        )


openrouter_qwen38_service = OpenRouterQwen38Service()
