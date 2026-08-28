from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import aiohttp

from bot.services.media_input_utils import image_sources_to_provider_safe_png_urls
from bot.services.rendergrid_service import (
    MIN_CREATION_POLL_INTERVAL_SECONDS,
    REFERENCE_IDENTITY_INSTRUCTION,
    REFERENCE_IDENTITY_MARKER,
    RenderGridClient,
    RenderGridError,
)

logger = logging.getLogger(__name__)

MIN_POLL_INTERVAL_SECONDS = MIN_CREATION_POLL_INTERVAL_SECONDS
DEFAULT_GENERATION_TIMEOUT_SECONDS = 600.0
POLICY_MARKERS = (
    "safety",
    "policy",
    "moderation",
    "prohibited",
    "blocked",
    "content violation",
)
REFERENCE_ONLY_PROMPT = (
    "Create the requested image using the provided reference image(s) as the visual source."
)
RenderGridProviderError = RenderGridError


class _NanoBananaRenderGridClient(RenderGridClient):
    def __init__(
        self,
        *args: Any,
        reference_guidance_enabled: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.reference_guidance_enabled = bool(reference_guidance_enabled)

    def _prepare_generation_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        prepared = dict(payload)
        prompt = str(prepared.get("prompt") or "").strip()
        references = self._normalize_reference_images(
            prepared.get("image_urls")
            if prepared.get("image_urls") is not None
            else prepared.get("reference_images")
        )
        if references:
            prepared["image_urls"] = references
            prepared.pop("reference_images", None)
            if (
                self.reference_guidance_enabled
                and REFERENCE_IDENTITY_MARKER not in prompt
            ):
                prepared["prompt"] = (
                    f"{REFERENCE_IDENTITY_INSTRUCTION}\n\nUser request:\n{prompt}"
                )
        else:
            prepared.pop("image_urls", None)
            prepared.pop("reference_images", None)
        return prepared


class RenderGridNanoBananaProvider:
    """Nano Banana 2/Pro adapter backed by the verified RenderGrid client.

    Local bot uploads are uploaded to RenderGrid `/uploads` and sent as
    `image_file_ids`; truly remote references are sent as `image_urls`. This is
    the same reference contract that passed the isolated RenderGrid bot test.
    Technical failures return None so the existing Nano Banana services fall
    back to KIE without any user-facing flow changes.
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
            or "https://api.rendergrid.io/api/public/v1"
        ).rstrip("/")
        self.request_timeout_seconds = float(
            request_timeout_seconds
            if request_timeout_seconds is not None
            else os.getenv("RENDERGRID_TIMEOUT_SECONDS", "60")
        )
        self.generation_timeout_seconds = float(
            generation_timeout_seconds
            if generation_timeout_seconds is not None
            else os.getenv(
                "RENDERGRID_GENERATION_TIMEOUT_SECONDS",
                str(DEFAULT_GENERATION_TIMEOUT_SECONDS),
            )
        )
        requested_poll = float(
            poll_interval_seconds
            if poll_interval_seconds is not None
            else os.getenv(
                "RENDERGRID_POLL_INTERVAL_SECONDS",
                str(MIN_POLL_INTERVAL_SECONDS),
            )
        )
        self.poll_interval_seconds = max(MIN_POLL_INTERVAL_SECONDS, requested_poll)
        self.max_references = max(1, int(max_references))
        self.reference_guidance_enabled = bool(reference_guidance_enabled)
        self.client = _NanoBananaRenderGridClient(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout_seconds=self.request_timeout_seconds,
            max_retries=max_retries,
            reference_guidance_enabled=self.reference_guidance_enabled,
        )
        self._download_session: aiohttp.ClientSession | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model_name and self.client.configured)

    @staticmethod
    def _creation_id(payload: Any) -> str | None:
        if not isinstance(payload, Mapping):
            return None
        for key in ("id", "creation_id", "task_id"):
            value = str(payload.get(key) or "").strip()
            if value:
                return value
        return RenderGridNanoBananaProvider._creation_id(payload.get("data"))

    @staticmethod
    def _status(payload: Any) -> str:
        if not isinstance(payload, Mapping):
            return ""
        value = str(payload.get("status") or payload.get("state") or "").strip().lower()
        return value or RenderGridNanoBananaProvider._status(payload.get("data"))

    def _normalize_references(self, image_input: list[str] | None) -> list[str]:
        if not image_input:
            return []
        normalized = image_sources_to_provider_safe_png_urls(
            list(image_input)[: self.max_references]
        )
        references: list[str] = []
        seen: set[str] = set()
        for source in normalized:
            if not isinstance(source, str):
                raise TypeError("RenderGrid reference source must be a public image URL")
            value = source.strip()
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(
                    "RenderGrid reference source is not publicly fetchable through HTTP(S)"
                )
            if value not in seen:
                seen.add(value)
                references.append(value)
        if image_input and not references:
            raise ValueError("RenderGrid received references but none are usable")
        return references

    @staticmethod
    def _normalize_resolution(resolution: str) -> str:
        value = str(resolution or "2K").strip().upper()
        value = {"BASIC": "2K", "HIGH": "4K"}.get(value, value)
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

    @staticmethod
    def _result_urls(payload: Any) -> list[str]:
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
        return RenderGridNanoBananaProvider._result_urls(payload.get("data"))

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

    async def _download_result(self, url: str) -> tuple[bytes, str]:
        if self._download_session is None or self._download_session.closed:
            self._download_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.request_timeout_seconds)
            )
        async with self._download_session.get(url) as response:
            if response.status != 200:
                raise RenderGridError(
                    f"RenderGrid result download failed ({response.status})",
                    status=response.status,
                )
            content = await response.read()
            if not content:
                raise RenderGridError("RenderGrid result download is empty")
            return content, response.content_type or "image/png"

    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
        resolution: str = "2K",
        image_input: list[str] | None = None,
        output_format: str = "png",
    ) -> dict[str, Any] | None:
        del output_format
        if not self.configured:
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
                return {
                    "error": "Nano Banana request has neither prompt nor reference image",
                    "provider": "rendergrid",
                    "provider_model": self.model_name,
                    "retryable": False,
                }

            logger.info(
                "Nano Banana provider request: provider=rendergrid model=%s refs=%s "
                "reference_contract=image_urls_or_file_ids aspect_ratio=%s resolution=%s prompt_len=%s",
                self.model_name,
                len(references),
                aspect_ratio,
                payload.get("resolution"),
                len(str(prompt or "")),
            )
            accepted = await self.client.generate_image(
                payload,
                idempotency_key=str(uuid4()),
            )
            creation_id = self._creation_id(accepted)
            final = accepted
            if creation_id and self._status(accepted) not in {"completed", "failed"}:
                final = await self.client.wait_for_creation(
                    creation_id,
                    timeout_seconds=self.generation_timeout_seconds,
                    poll_interval_seconds=self.poll_interval_seconds,
                )

            if self._status(final) == "failed":
                reason = self._failure_text(final) or "RenderGrid generation failed"
                if self._is_policy_failure(reason):
                    return {
                        "error": reason,
                        "provider": "rendergrid",
                        "provider_model": self.model_name,
                        "creation_id": creation_id,
                        "retryable": False,
                    }
                raise RenderGridError(reason, payload=final)

            result_urls = self._result_urls(final)
            if not result_urls:
                raise RenderGridError(
                    "RenderGrid completed without result_urls",
                    payload=final,
                )
            image_bytes, mime_type = await self._download_result(result_urls[0])
            logger.info(
                "Nano Banana provider success: provider=rendergrid model=%s refs=%s "
                "creation_id=%s latency_seconds=%.2f bytes=%s",
                self.model_name,
                len(references),
                creation_id or "none",
                asyncio.get_running_loop().time() - started_at,
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
        except (RenderGridError, ValueError, TypeError, TimeoutError) as exc:
            status = exc.status if isinstance(exc, RenderGridError) else None
            code = exc.code if isinstance(exc, RenderGridError) else None
            if isinstance(exc, RenderGridError) and self._is_policy_failure(str(exc), code):
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
                asyncio.get_running_loop().time() - started_at,
                exc,
            )
            return None

    async def close(self) -> None:
        if self._download_session is not None and not self._download_session.closed:
            await self._download_session.close()
