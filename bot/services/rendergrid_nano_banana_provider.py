from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse
from uuid import uuid4

import aiohttp

from bot.services.media_input_utils import image_sources_to_provider_safe_png_urls

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.rendergrid.io/api/public/v1"
MIN_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_GENERATION_TIMEOUT_SECONDS = 600.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 60.0
RETRYABLE_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
TERMINAL_STATUSES = frozenset({"completed", "failed"})
POLICY_MARKERS = (
    "safety",
    "policy",
    "moderation",
    "prohibited",
    "blocked",
    "content violation",
)
REFERENCE_GUIDANCE = (
    "Use the provided reference image(s) as authoritative visual references. "
    "Preserve the identity and distinctive characteristics of any person, product, "
    "object, clothing, or scene that the user's request intends to keep. Do not "
    "replace a referenced subject with a lookalike or invented substitute unless "
    "the user explicitly asks for that change."
)
REFERENCE_ONLY_PROMPT = (
    "Create the requested image using the provided reference image(s) as the visual source."
)


@dataclass(slots=True)
class RenderGridProviderError(RuntimeError):
    message: str
    status: int | None = None
    code: str | None = None
    payload: Any = None
    retry_after: float | None = None

    def __str__(self) -> str:
        return self.message


class RenderGridNanoBananaProvider:
    """Nano Banana adapter for RenderGrid with the bot's existing sync result contract.

    The public bot flow expects image bytes for synchronous providers. RenderGrid itself is
    asynchronous, so this adapter creates a RenderGrid creation, polls it no faster than the
    documented five-second floor, downloads the first result image, and returns ``image_bytes``.
    Technical failures return ``None`` so the existing Nano Banana service transparently falls
    through to its queued KIE path. Explicit provider policy refusals are returned as a terminal
    non-retryable result and are not hidden behind a provider switch.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        base_url: str | None = None,
        request_timeout_seconds: float | None = None,
        generation_timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        max_retries: int = 2,
        max_references: int = 8,
        reference_guidance_enabled: bool = True,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.model_name = str(model_name or "").strip()
        self.base_url = (
            base_url
            or os.getenv("RENDERGRID_BASE_URL", "")
            or DEFAULT_BASE_URL
        ).rstrip("/")
        self.request_timeout_seconds = float(
            request_timeout_seconds
            if request_timeout_seconds is not None
            else os.getenv("RENDERGRID_TIMEOUT_SECONDS", DEFAULT_REQUEST_TIMEOUT_SECONDS)
        )
        self.generation_timeout_seconds = float(
            generation_timeout_seconds
            if generation_timeout_seconds is not None
            else os.getenv(
                "RENDERGRID_GENERATION_TIMEOUT_SECONDS",
                DEFAULT_GENERATION_TIMEOUT_SECONDS,
            )
        )
        configured_poll_interval = float(
            poll_interval_seconds
            if poll_interval_seconds is not None
            else os.getenv("RENDERGRID_POLL_INTERVAL_SECONDS", MIN_POLL_INTERVAL_SECONDS)
        )
        self.poll_interval_seconds = max(
            MIN_POLL_INTERVAL_SECONDS,
            configured_poll_interval,
        )
        self.max_retries = max(0, int(max_retries))
        self.max_references = max(1, int(max_references))
        self.reference_guidance_enabled = bool(reference_guidance_enabled)
        self._session: aiohttp.ClientSession | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model_name)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.request_timeout_seconds)
            )
        return self._session

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        if not self.api_key:
            raise RenderGridProviderError("RENDERGRID_API_KEY is not configured")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    @staticmethod
    def _decode_payload(raw: str) -> Any:
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"message": raw}

    @staticmethod
    def _error_details(payload: Any, status: int) -> tuple[str, str | None]:
        if isinstance(payload, Mapping):
            error = payload.get("error")
            if isinstance(error, Mapping):
                message = str(
                    error.get("message")
                    or error.get("detail")
                    or payload.get("message")
                    or f"RenderGrid request failed ({status})"
                )
                code = error.get("code") or payload.get("code")
                return message, str(code) if code is not None else None
            if isinstance(error, str) and error.strip():
                return error.strip(), str(payload.get("code") or "") or None
            message = str(
                payload.get("message")
                or payload.get("detail")
                or f"RenderGrid request failed ({status})"
            )
            code = payload.get("code")
            return message, str(code) if code is not None else None
        return f"RenderGrid request failed ({status})", None

    @staticmethod
    def _retry_after_seconds(response: aiohttp.ClientResponse, attempt: int) -> float:
        raw = response.headers.get("Retry-After", "").strip()
        if raw:
            try:
                return max(0.0, min(float(raw), 30.0))
            except ValueError:
                pass
        return min(2.0**attempt, 8.0)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        session = await self._get_session()
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_error: RenderGridProviderError | None = None

        for attempt in range(self.max_retries + 1):
            try:
                async with session.request(
                    method.upper(),
                    url,
                    headers=self._headers(idempotency_key=idempotency_key),
                    json=dict(json_body) if json_body is not None else None,
                ) as response:
                    raw = await response.text()
                    payload = self._decode_payload(raw)
                    if 200 <= response.status < 300:
                        return payload

                    message, code = self._error_details(payload, response.status)
                    retry_after = self._retry_after_seconds(response, attempt)
                    last_error = RenderGridProviderError(
                        message=message,
                        status=response.status,
                        code=code,
                        payload=payload,
                        retry_after=retry_after,
                    )
                    if (
                        response.status not in RETRYABLE_STATUS_CODES
                        or attempt >= self.max_retries
                    ):
                        raise last_error
                    await asyncio.sleep(retry_after)
            except RenderGridProviderError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_error = RenderGridProviderError(
                    message=f"RenderGrid network error: {type(exc).__name__}",
                    payload={"exception": type(exc).__name__},
                )
                if attempt >= self.max_retries:
                    raise last_error from exc
                await asyncio.sleep(min(2.0**attempt, 8.0))

        if last_error is not None:
            raise last_error
        raise RenderGridProviderError("RenderGrid request failed")

    @staticmethod
    def _extract_creation_id(payload: Any) -> str | None:
        if not isinstance(payload, Mapping):
            return None
        for key in ("id", "creation_id", "task_id"):
            value = str(payload.get(key) or "").strip()
            if value:
                return value
        return RenderGridNanoBananaProvider._extract_creation_id(payload.get("data"))

    @staticmethod
    def _extract_status(payload: Any) -> str:
        if not isinstance(payload, Mapping):
            return ""
        status = str(payload.get("status") or payload.get("state") or "").strip().lower()
        if status:
            return status
        return RenderGridNanoBananaProvider._extract_status(payload.get("data"))

    @staticmethod
    def _extract_result_urls(payload: Any) -> list[str]:
        if not isinstance(payload, Mapping):
            return []
        for key in ("result_urls", "urls", "images", "outputs"):
            raw = payload.get(key)
            if not isinstance(raw, list):
                continue
            urls: list[str] = []
            for item in raw:
                if isinstance(item, str):
                    value = item
                elif isinstance(item, Mapping):
                    value = str(item.get("url") or item.get("image_url") or "")
                else:
                    continue
                if value.startswith(("http://", "https://")):
                    urls.append(value)
            if urls:
                return urls
        return RenderGridNanoBananaProvider._extract_result_urls(payload.get("data"))

    @staticmethod
    def _failure_text(payload: Any) -> str:
        if not isinstance(payload, Mapping):
            return str(payload or "")
        for key in ("error", "message", "detail", "failMsg", "failure_reason"):
            value = payload.get(key)
            if isinstance(value, Mapping):
                nested = RenderGridNanoBananaProvider._failure_text(value)
                if nested:
                    return nested
            elif value:
                return str(value)
        return RenderGridNanoBananaProvider._failure_text(payload.get("data"))

    @staticmethod
    def _is_policy_failure(message: str, code: str | None = None) -> bool:
        value = f"{code or ''} {message or ''}".lower()
        return any(marker in value for marker in POLICY_MARKERS)

    def _normalize_references(self, image_input: list[str] | None) -> list[str]:
        if not image_input:
            return []
        normalized_sources = image_sources_to_provider_safe_png_urls(
            list(image_input)[: self.max_references]
        )
        references: list[str] = []
        for source in normalized_sources:
            if not isinstance(source, str):
                raise TypeError("RenderGrid reference source must be a public image URL")
            value = source.strip()
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(
                    "RenderGrid reference source is not publicly fetchable through HTTP(S)"
                )
            references.append(value)
        if image_input and not references:
            raise ValueError("RenderGrid received references but none are usable")
        return references

    @staticmethod
    def _normalize_resolution(resolution: str) -> str:
        value = str(resolution or "2K").strip().upper()
        aliases = {"BASIC": "2K", "HIGH": "4K"}
        value = aliases.get(value, value)
        return value if value in {"1K", "2K", "4K"} else "2K"

    def _build_payload(
        self,
        *,
        prompt: str,
        aspect_ratio: str,
        resolution: str,
        references: list[str],
    ) -> dict[str, Any]:
        provider_prompt = str(prompt or "").strip()
        if not provider_prompt and references:
            provider_prompt = REFERENCE_ONLY_PROMPT
        if references and self.reference_guidance_enabled:
            provider_prompt = f"{REFERENCE_GUIDANCE}\n\nUser request:\n{provider_prompt}"

        payload: dict[str, Any] = {
            "model": self.model_name,
            "prompt": provider_prompt,
            "resolution": self._normalize_resolution(resolution),
        }
        ratio = str(aspect_ratio or "").strip()
        if ratio and ratio.lower() != "auto":
            payload["aspect_ratio"] = ratio
        if references:
            payload["reference_images"] = references
        return payload

    async def _wait_for_creation(self, creation_id: str) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + self.generation_timeout_seconds
        encoded_creation_id = quote(creation_id, safe="")
        while True:
            creation = await self._request("GET", f"/creations/{encoded_creation_id}")
            if not isinstance(creation, dict):
                raise RenderGridProviderError(
                    "RenderGrid returned an invalid creation response",
                    payload=creation,
                )
            status = self._extract_status(creation)
            if status in TERMINAL_STATUSES:
                return creation
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"RenderGrid creation {creation_id} timed out")
            await asyncio.sleep(self.poll_interval_seconds)

    async def _download_result(self, url: str) -> tuple[bytes, str]:
        session = await self._get_session()
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=self.request_timeout_seconds),
        ) as response:
            if response.status != 200:
                raise RenderGridProviderError(
                    f"RenderGrid result download failed ({response.status})",
                    status=response.status,
                )
            content = await response.read()
            if not content:
                raise RenderGridProviderError("RenderGrid result download is empty")
            return content, response.content_type or "image/png"

    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
        resolution: str = "2K",
        image_input: list[str] | None = None,
        output_format: str = "png",
    ) -> dict[str, Any] | None:
        del output_format  # RenderGrid model output format stays provider-controlled.
        if not self.configured:
            logger.info(
                "RenderGrid Nano Banana disabled at runtime: model=%s configured=%s",
                self.model_name,
                self.configured,
            )
            return None

        started_at = asyncio.get_running_loop().time()
        try:
            references = self._normalize_references(image_input)
            payload = self._build_payload(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                references=references,
            )
            if not str(payload.get("prompt") or "").strip():
                logger.warning(
                    "RenderGrid Nano Banana request has neither prompt nor references: model=%s",
                    self.model_name,
                )
                return {
                    "error": "Nano Banana request has neither prompt nor reference image",
                    "provider": "rendergrid",
                    "provider_model": self.model_name,
                    "retryable": False,
                }

            logger.info(
                "Nano Banana provider request: provider=rendergrid model=%s refs=%s "
                "aspect_ratio=%s resolution=%s prompt_len=%s",
                self.model_name,
                len(references),
                aspect_ratio,
                payload.get("resolution"),
                len(str(prompt or "")),
            )
            accepted = await self._request(
                "POST",
                "/images/generate",
                json_body=payload,
                idempotency_key=str(uuid4()),
            )
            if not isinstance(accepted, dict):
                raise RenderGridProviderError(
                    "RenderGrid returned an invalid generation response",
                    payload=accepted,
                )

            creation_id = self._extract_creation_id(accepted)
            final = accepted
            if creation_id and self._extract_status(accepted) not in TERMINAL_STATUSES:
                final = await self._wait_for_creation(creation_id)

            status = self._extract_status(final)
            if status == "failed":
                reason = self._failure_text(final) or "RenderGrid generation failed"
                if self._is_policy_failure(reason):
                    logger.warning(
                        "Nano Banana provider policy refusal: provider=rendergrid model=%s "
                        "creation_id=%s reason=%s",
                        self.model_name,
                        creation_id or "none",
                        reason[:500],
                    )
                    return {
                        "error": reason,
                        "provider": "rendergrid",
                        "provider_model": self.model_name,
                        "creation_id": creation_id,
                        "retryable": False,
                    }
                raise RenderGridProviderError(reason, payload=final)

            result_urls = self._extract_result_urls(final)
            if not result_urls:
                raise RenderGridProviderError(
                    "RenderGrid completed without result_urls",
                    payload=final,
                )
            image_bytes, mime_type = await self._download_result(result_urls[0])
            latency = asyncio.get_running_loop().time() - started_at
            logger.info(
                "Nano Banana provider success: provider=rendergrid model=%s refs=%s "
                "creation_id=%s latency_seconds=%.2f bytes=%s",
                self.model_name,
                len(references),
                creation_id or "none",
                latency,
                len(image_bytes),
            )
            return {
                "image_bytes": image_bytes,
                "mime_type": mime_type,
                "provider": "rendergrid",
                "provider_model": self.model_name,
                "creation_id": creation_id,
                "result_url": result_urls[0],
                "retryable": False,
            }
        except (RenderGridProviderError, ValueError, TypeError, TimeoutError) as exc:
            latency = asyncio.get_running_loop().time() - started_at
            status = exc.status if isinstance(exc, RenderGridProviderError) else None
            code = exc.code if isinstance(exc, RenderGridProviderError) else None
            if isinstance(exc, RenderGridProviderError) and self._is_policy_failure(
                str(exc), code
            ):
                return {
                    "error": str(exc),
                    "provider": "rendergrid",
                    "provider_model": self.model_name,
                    "http_status": status,
                    "retryable": False,
                }
            logger.warning(
                "Nano Banana provider technical failure: provider=rendergrid model=%s "
                "status=%s code=%s latency_seconds=%.2f error=%s; fallback=kie",
                self.model_name,
                status,
                code,
                latency,
                exc,
            )
            return None

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
