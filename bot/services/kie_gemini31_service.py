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

_CONTENT_VALIDATION_ERRORS = (
    AssertionError,
    KeyError,
    TypeError,
    ValueError,
    RuntimeError,
)


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


def _extract_chat_content(data: Any) -> str:
    """Extract text from KIE/OpenAI-compatible chat completions safely."""

    if not isinstance(data, dict):
        raise TypeError("response body must be an object")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise KeyError("choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise TypeError("choice must be an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise KeyError("message")
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n".join(parts).strip()
    raise TypeError("message.content must be text or text blocks")


def _safe_response_shape(data: Any) -> str:
    """Return bounded structural metadata without response/user content."""

    if not isinstance(data, dict):
        return f"body_type={type(data).__name__}"
    keys = ",".join(sorted(str(key) for key in data)[:12])
    choices = data.get("choices")
    choices_type = type(choices).__name__
    choices_len = len(choices) if isinstance(choices, list) else -1
    content_type = "missing"
    finish_reason = ""
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        finish_reason = str(choices[0].get("finish_reason") or "")[:32]
        message = choices[0].get("message")
        if isinstance(message, dict):
            content_type = type(message.get("content")).__name__
    raw_code = data.get("code")
    code = str(raw_code)[:16] if raw_code is not None else ""
    return (
        f"keys={keys} choices_type={choices_type} choices_len={choices_len} "
        f"content_type={content_type} finish_reason={finish_reason} body_code={code}"
    )


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
        media_kind: str = "image",
        user_instruction: str,
        system_prompt: str | None = None,
        content_validator: Callable[[str], Any] | None = None,
    ) -> str:
        trace = _analysis_trace.get() or MediaAnalysisTrace()
        trace.provider = "kie_gemini31"
        if media_kind not in {"image", "video"}:
            raise ValueError("media_kind must be image or video")
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

        async def kie_fallback(
            session: aiohttp.ClientSession,
            error: str,
        ) -> str:
            fallback_model = str(
                config.KIE_MEDIA_ANALYSIS_FALLBACK_MODEL or ""
            ).strip()
            fallback_endpoint = str(
                config.KIE_MEDIA_ANALYSIS_FALLBACK_ENDPOINT or ""
            ).strip()
            fallback_attempts = max(
                1,
                min(3, int(config.KIE_MEDIA_ANALYSIS_FALLBACK_MAX_ATTEMPTS)),
            )
            if not fallback_model or not fallback_endpoint:
                trace.log("provider_failure", error=error)
                raise RuntimeError("KIE Gemini fallback is not configured")

            fallback_payload = dict(payload)
            # KIE routes this OpenAI-compatible API by the model-specific endpoint.
            # Its documented request body omits `model`; sending it made video
            # analysis stall in live contract testing while the same request
            # completed normally without the field.
            fallback_payload.pop("model", None)
            trace.provider = "kie_gemini_fallback"
            trace.log("fallback", error=error)

            for fallback_attempt in range(1, fallback_attempts + 1):
                try:
                    async with session.post(
                        self.base_url + fallback_endpoint,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=fallback_payload,
                    ) as response:
                        logger.info(
                            "media_analysis provider=kie model=%s request_id=%s "
                            "attempt=%s status=%s fallback=true elapsed_ms=%s",
                            fallback_model,
                            request_id,
                            fallback_attempt,
                            response.status,
                            int((time.monotonic() - started) * 1000),
                        )
                        if (
                            response.status == 429 or response.status >= 500
                        ) and fallback_attempt < fallback_attempts:
                            await asyncio.sleep(2 ** (fallback_attempt - 1))
                            continue
                        if response.status >= 400:
                            trace.log(
                                "provider_failure",
                                error="fallback_http_error",
                                status=response.status,
                            )
                            raise RuntimeError(
                                f"KIE Gemini fallback: HTTP {response.status} "
                                f"(request_id={request_id})"
                            )

                        data: Any = await response.json(content_type=None)
                        body_code = 0
                        if isinstance(data, dict):
                            try:
                                body_code = int(data.get("code", 0) or 0)
                            except (TypeError, ValueError):
                                body_code = 0
                        if body_code >= 400:
                            logger.warning(
                                "media_analysis provider=kie model=%s request_id=%s "
                                "attempt=%s fallback=true body_code=%s shape=%s",
                                fallback_model,
                                request_id,
                                fallback_attempt,
                                body_code,
                                _safe_response_shape(data),
                            )
                            if (
                                body_code >= 500
                                and fallback_attempt < fallback_attempts
                            ):
                                await asyncio.sleep(2 ** (fallback_attempt - 1))
                                continue
                            trace.log(
                                "provider_failure",
                                error=f"fallback_body_{body_code}",
                                status=response.status,
                            )
                            raise RuntimeError(
                                f"KIE Gemini fallback returned code {body_code}"
                            )

                        try:
                            content = _extract_chat_content(data)
                        except (KeyError, IndexError, TypeError) as exc:
                            if fallback_attempt < fallback_attempts:
                                await asyncio.sleep(2 ** (fallback_attempt - 1))
                                continue
                            trace.log(
                                "provider_failure",
                                error="fallback_invalid_response",
                                status=response.status,
                            )
                            raise RuntimeError(
                                "KIE Gemini fallback returned an invalid response"
                            ) from exc
                        if not content:
                            if fallback_attempt < fallback_attempts:
                                await asyncio.sleep(2 ** (fallback_attempt - 1))
                                continue
                            trace.log(
                                "provider_failure",
                                error="fallback_empty_content",
                                status=response.status,
                            )
                            raise RuntimeError(
                                "KIE Gemini fallback returned empty content"
                            )

                        if content_validator is not None:
                            try:
                                content_validator(content)
                            except _CONTENT_VALIDATION_ERRORS as exc:
                                logger.warning(
                                    "media_analysis provider=kie model=%s request_id=%s "
                                    "attempt=%s fallback=true semantic_invalid=%s",
                                    fallback_model,
                                    request_id,
                                    fallback_attempt,
                                    type(exc).__name__,
                                )
                                if fallback_attempt < fallback_attempts:
                                    await asyncio.sleep(2 ** (fallback_attempt - 1))
                                    continue
                                trace.log(
                                    "provider_failure",
                                    error="fallback_invalid_content",
                                    status=response.status,
                                )
                                raise RuntimeError(
                                    "KIE Gemini fallback returned unusable content"
                                ) from exc

                        trace.log("provider_success", status=response.status)
                        return content
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    logger.warning(
                        "media_analysis provider=kie model=%s request_id=%s "
                        "attempt=%s fallback=true error=%s",
                        fallback_model,
                        request_id,
                        fallback_attempt,
                        type(exc).__name__,
                    )
                    if fallback_attempt < fallback_attempts:
                        await asyncio.sleep(2 ** (fallback_attempt - 1))
                        continue
                    trace.log(
                        "provider_failure",
                        error=f"fallback_{type(exc).__name__}",
                    )
                    raise RuntimeError(
                        f"KIE Gemini fallback network failure "
                        f"(request_id={request_id})"
                    ) from exc

            raise RuntimeError("KIE Gemini fallback exhausted attempts")

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
                            if response.status == 429 or response.status >= 500:
                                return await kie_fallback(
                                    session, f"kie_http_{response.status}"
                                )
                            trace.log(
                                "provider_failure",
                                error="http_error",
                                status=response.status,
                            )
                            raise RuntimeError(
                                f"KIE Gemini 3.1 Pro: HTTP {response.status} (request_id={request_id})"
                            )
                        data: Any = None
                        try:
                            data = await response.json(content_type=None)
                            if isinstance(data, dict):
                                try:
                                    body_code = int(data.get("code", 0) or 0)
                                except (TypeError, ValueError):
                                    body_code = 0
                                if body_code >= 500:
                                    logger.warning(
                                        "media_analysis provider=kie model=%s request_id=%s "
                                        "attempt=%s transient_body_code=%s shape=%s",
                                        self.MODEL,
                                        request_id,
                                        attempt,
                                        body_code,
                                        _safe_response_shape(data),
                                    )
                                    return await kie_fallback(
                                        session, f"kie_body_{body_code}"
                                    )
                            content = _extract_chat_content(data)
                        except (
                            json.JSONDecodeError,
                            KeyError,
                            IndexError,
                            TypeError,
                        ):
                            logger.warning(
                                "media_analysis provider=kie model=%s request_id=%s "
                                "attempt=%s retryable=invalid_response status=%s shape=%s",
                                self.MODEL,
                                request_id,
                                attempt,
                                response.status,
                                _safe_response_shape(data),
                            )
                            if attempt < attempts:
                                trace.log(
                                    "provider_retry",
                                    error="invalid_response",
                                    status=response.status,
                                )
                                await asyncio.sleep(2 ** (attempt - 1))
                                continue
                            return await kie_fallback(session, "invalid_response")
                        if not content:
                            logger.warning(
                                "media_analysis provider=kie model=%s request_id=%s "
                                "attempt=%s retryable=empty_content status=%s shape=%s",
                                self.MODEL,
                                request_id,
                                attempt,
                                response.status,
                                _safe_response_shape(data),
                            )
                            if attempt < attempts:
                                trace.log(
                                    "provider_retry",
                                    error="empty_content",
                                    status=response.status,
                                )
                                await asyncio.sleep(2 ** (attempt - 1))
                                continue
                            return await kie_fallback(session, "empty_content")

                        if content_validator is not None:
                            try:
                                content_validator(content)
                            except _CONTENT_VALIDATION_ERRORS as exc:
                                logger.warning(
                                    "media_analysis provider=kie model=%s request_id=%s "
                                    "attempt=%s semantic_invalid=%s status=%s",
                                    self.MODEL,
                                    request_id,
                                    attempt,
                                    type(exc).__name__,
                                    response.status,
                                )
                                return await kie_fallback(
                                    session, "invalid_content"
                                )

                        trace.log("provider_success", status=response.status)
                        return content
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    logger.warning(
                        "media_analysis provider=kie model=%s request_id=%s attempt=%s error=%s",
                        self.MODEL,
                        request_id,
                        attempt,
                        type(exc).__name__,
                    )
                    if attempt == attempts:
                        return await kie_fallback(session, type(exc).__name__)
                    await asyncio.sleep(2 ** (attempt - 1))
        raise RuntimeError("KIE Gemini 3.1 Pro exhausted attempts")
