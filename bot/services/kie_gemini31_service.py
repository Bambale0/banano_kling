"""KIE Gemini 3.1 Pro native photo/video analysis adapter."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, ParamSpec, TypeVar

import aiohttp

from bot.config import config
from bot.database import get_bot_setting

logger = logging.getLogger(__name__)
MEDIA_ANALYSIS_PROVIDERS = frozenset({"kie_gemini31", "qwen38"})


@dataclass
class MediaAnalysisTrace:
    """One bounded analysis operation, including provider fallback attempts."""

    telegram_user_id: int | None = None
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    provider: str = "existing"
    instruction_revision: str = ""
    started: float = field(default_factory=time.monotonic)

    def log(self, event: str, *, error: str = "", status: int | None = None) -> None:
        logger.info(
            "media_analysis event=%s provider=%s request_id=%s user_id=%s status=%s error=%s elapsed_ms=%s instruction_revision=%s",
            event,
            self.provider,
            self.request_id,
            self.telegram_user_id,
            status,
            error,
            int((time.monotonic() - self.started) * 1000),
            self.instruction_revision,
            extra={
                "analysis_event": event,
                "analysis_instruction_revision": self.instruction_revision,
                "analysis_provider": self.provider,
                "request_id": self.request_id,
                "telegram_user_id": self.telegram_user_id,
                "error_category": error,
            },
        )


_analysis_trace: ContextVar[MediaAnalysisTrace | None] = ContextVar(
    "media_analysis_trace", default=None
)


_P = ParamSpec("_P")
_R = TypeVar("_R")


def trace_media_analysis(
    method: Callable[_P, Awaitable[_R]],
) -> Callable[_P, Awaitable[_R]]:
    """Keep a task-local correlation ID through the existing fallback chain."""

    @wraps(method)
    async def traced(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        trace = MediaAnalysisTrace(telegram_user_id=kwargs.get("telegram_user_id"))
        token = _analysis_trace.set(trace)
        try:
            result = await method(*args, **kwargs)
        except Exception as exc:
            trace.log("operation_failure", error=type(exc).__name__)
            raise
        else:
            trace.log("operation_success")
            return result
        finally:
            _analysis_trace.reset(token)

    return traced


def trace_analysis_provider(
    provider: str, *, fallback_error: Exception | None = None
) -> None:
    trace = _analysis_trace.get()
    if trace is not None:
        trace.provider = provider
        if provider != "kie_gemini31":
            trace.instruction_revision = ""
        if fallback_error is not None:
            trace.log("fallback", error=type(fallback_error).__name__)


def trace_analysis_instructions(revision: str) -> None:
    """Associate the effective guidance version with this analysis outcome."""
    trace = _analysis_trace.get()
    if trace is not None:
        trace.provider = "kie_gemini31"
        trace.instruction_revision = revision
        trace.log("instructions_selected")


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
        self.base_url = (config.KIE_BASE_URL if base_url is None else base_url).rstrip(
            "/"
        )

    async def analyze_media(
        self,
        *,
        media_url: str,
        user_instruction: str,
        system_prompt: str | None = None,
    ) -> str:
        trace = _analysis_trace.get() or MediaAnalysisTrace()
        trace.provider = "kie_gemini31"
        if not self.api_key:
            trace.log("provider_failure", error="missing_credentials")
            raise RuntimeError("KIE_AI_API_KEY is not configured for media analysis")
        if not media_url.strip():
            trace.log("provider_failure", error="missing_media")
            raise ValueError("media_url is required")
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_instruction},
                    {"type": "image_url", "image_url": {"url": media_url}},
                ],
            }
        )
        payload = {
            "messages": messages,
            "stream": False,
            "include_thoughts": False,
            "reasoning_effort": "high",
        }
        attempts = max(1, min(3, config.KIE_MEDIA_ANALYSIS_MAX_ATTEMPTS))
        timeout = aiohttp.ClientTimeout(
            total=max(1, min(300, config.KIE_MEDIA_ANALYSIS_TIMEOUT_SECONDS))
        )
        request_id = trace.request_id
        started = time.monotonic()
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in range(1, attempts + 1):
                try:
                    async with session.post(
                        self.base_url + self.ENDPOINT,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=payload,
                    ) as response:
                        logger.info(
                            "media_analysis provider=kie model=%s request_id=%s attempt=%s status=%s elapsed_ms=%s",
                            self.MODEL,
                            request_id,
                            attempt,
                            response.status,
                            int((time.monotonic() - started) * 1000),
                        )
                        if (
                            response.status == 429 or response.status >= 500
                        ) and attempt < attempts:
                            await asyncio.sleep(2 ** (attempt - 1))
                            continue
                        if response.status >= 400:
                            trace.log(
                                "provider_failure",
                                error="http_error",
                                status=response.status,
                            )
                            raise RuntimeError(
                                f"KIE Gemini 3.1 Pro: HTTP {response.status} (request_id={request_id})"
                            )
                        try:
                            data = await response.json(content_type=None)
                            content = data["choices"][0]["message"]["content"]
                        except (
                            json.JSONDecodeError,
                            KeyError,
                            IndexError,
                            TypeError,
                        ) as exc:
                            trace.log(
                                "provider_failure",
                                error="invalid_response",
                                status=response.status,
                            )
                            raise RuntimeError(
                                "KIE Gemini 3.1 Pro returned an invalid response"
                            ) from exc
                        if not isinstance(content, str) or not content.strip():
                            trace.log(
                                "provider_failure",
                                error="empty_content",
                                status=response.status,
                            )
                            raise RuntimeError(
                                "KIE Gemini 3.1 Pro returned empty content"
                            )
                        trace.log("provider_success", status=response.status)
                        return content.strip()
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    logger.warning(
                        "media_analysis provider=kie model=%s request_id=%s attempt=%s error=%s",
                        self.MODEL,
                        request_id,
                        attempt,
                        type(exc).__name__,
                    )
                    if attempt == attempts:
                        trace.log("provider_failure", error=type(exc).__name__)
                        raise RuntimeError(
                            f"KIE Gemini 3.1 Pro network failure (request_id={request_id})"
                        ) from exc
                    await asyncio.sleep(2 ** (attempt - 1))
        raise RuntimeError("KIE Gemini 3.1 Pro exhausted attempts")
