from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from typing import Any, Iterable, Optional

import aiohttp

from bot.services.media_input_utils import image_sources_to_data_uris

logger = logging.getLogger(__name__)

_SUPPORTED_ASPECT_RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4"}
_TERMINAL_STATUSES = {"completed", "failed"}
_MAX_RESULT_BYTES = 25 * 1024 * 1024


def build_nexus_image_params(
    *,
    model_name: str,
    prompt: str,
    aspect_ratio: str,
    image_input: Iterable[str | bytes | bytearray] | None = None,
    max_references: int = 4,
) -> dict[str, Any]:
    """Build the documented Nexus image-generation params payload.

    Nexus' public Nano Banana schema exposes model_name, prompt, aspect_ratio and
    image references. Resolution/output-format controls are intentionally not
    sent because they are not part of the published Nano Banana Nexus contract.
    """

    params: dict[str, Any] = {
        "model_name": str(model_name).strip(),
        "prompt": str(prompt or "").strip(),
    }

    ratio = str(aspect_ratio or "").strip()
    if ratio and ratio.lower() != "auto" and ratio in _SUPPORTED_ASPECT_RATIOS:
        params["aspect_ratio"] = ratio

    references = [
        value
        for value in image_sources_to_data_uris(image_input)
        if isinstance(value, str) and value.strip()
    ][: max(0, int(max_references))]

    if len(references) == 1:
        params["image_url"] = references[0]
    elif references:
        params["image_urls"] = references

    return params


def _extract_result_source(payload: dict[str, Any]) -> tuple[str, str] | None:
    result = payload.get("result")
    if isinstance(result, str) and result.strip():
        value = result.strip()
        return ("url", value) if value.startswith(("http://", "https://")) else ("base64", value)
    if not isinstance(result, dict):
        return None

    for key in ("image_url", "url"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return "url", value.strip()

    for key in ("images", "image_urls"):
        values = result.get(key)
        if not isinstance(values, list) or not values:
            continue
        first = values[0]
        if isinstance(first, str) and first.strip():
            value = first.strip()
            return ("url", value) if value.startswith(("http://", "https://")) else ("base64", value)
        if isinstance(first, dict):
            for nested_key in ("image_url", "url", "base64", "b64_json"):
                value = first.get(nested_key)
                if isinstance(value, str) and value.strip():
                    normalized = value.strip()
                    return (
                        ("url", normalized)
                        if normalized.startswith(("http://", "https://"))
                        else ("base64", normalized)
                    )

    for key in ("base64", "b64_json", "image_base64"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return "base64", value.strip()
    return None


def _decode_base64_image(value: str) -> tuple[bytes, str]:
    normalized = str(value or "").strip()
    mime_type = "image/png"
    encoded = normalized
    if normalized.startswith("data:") and "," in normalized:
        header, encoded = normalized.split(",", 1)
        if ";base64" in header:
            mime_type = header.removeprefix("data:").split(";", 1)[0] or mime_type

    raw = base64.b64decode(encoded, validate=False)
    if not raw:
        raise ValueError("empty image result")
    if len(raw) > _MAX_RESULT_BYTES:
        raise ValueError("image result exceeds 25 MB")
    return raw, mime_type


class NexusImageProvider:
    """Synchronous adapter over Nexus' async /generate + /tasks flow."""

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        base_url: str = "https://nexusapi.dev",
        timeout_seconds: int = 180,
        poll_interval_seconds: float = 1.0,
        max_references: int = 4,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.model_name = str(model_name or "").strip()
        self.base_url = str(base_url or "https://nexusapi.dev").strip().rstrip("/")
        self.timeout_seconds = max(30, int(timeout_seconds))
        self.poll_interval_seconds = max(0.5, float(poll_interval_seconds))
        self.max_references = max(1, int(max_references))
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds + 60)
            )
        return self._session

    async def _start_task(self, session: aiohttp.ClientSession, params: dict[str, Any]) -> str | None:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": str(uuid.uuid4()),
        }
        try:
            async with session.post(
                f"{self.base_url}/generate",
                headers=headers,
                json={"params": params},
            ) as response:
                body = await response.text()
                if response.status not in {200, 202}:
                    logger.warning(
                        "Nexus %s start failed: HTTP %s body=%s",
                        self.model_name,
                        response.status,
                        body[:1000],
                    )
                    return None
                try:
                    payload = await response.json(content_type=None)
                except Exception:
                    logger.warning("Nexus %s start response is not JSON", self.model_name)
                    return None
                task_id = str(payload.get("task_id") or "").strip() if isinstance(payload, dict) else ""
                if not task_id:
                    logger.warning("Nexus %s did not return task_id", self.model_name)
                    return None
                return task_id
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning("Nexus %s start transport failure: %s", self.model_name, exc)
            return None

    async def _wait_for_result(
        self,
        session: aiohttp.ClientSession,
        task_id: str,
    ) -> dict[str, Any] | None:
        deadline = asyncio.get_running_loop().time() + self.timeout_seconds
        headers = {"Authorization": f"Bearer {self.api_key}"}

        while asyncio.get_running_loop().time() < deadline:
            try:
                async with session.get(
                    f"{self.base_url}/tasks/{task_id}",
                    headers=headers,
                ) as response:
                    if response.status != 200:
                        body = await response.text()
                        logger.warning(
                            "Nexus %s task %s status failed: HTTP %s body=%s",
                            self.model_name,
                            task_id,
                            response.status,
                            body[:1000],
                        )
                        return None
                    payload = await response.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
                logger.warning(
                    "Nexus %s task %s polling failure: %s",
                    self.model_name,
                    task_id,
                    exc,
                )
                return None

            if not isinstance(payload, dict):
                return None
            status = str(payload.get("status") or "").strip().lower()
            if status == "completed":
                return payload
            if status == "failed":
                logger.warning(
                    "Nexus %s task %s failed: %s",
                    self.model_name,
                    task_id,
                    str(payload.get("error") or "unknown provider failure")[:1000],
                )
                return None
            if status not in _TERMINAL_STATUSES:
                await asyncio.sleep(self.poll_interval_seconds)

        logger.warning(
            "Nexus %s task %s timed out after %ss",
            self.model_name,
            task_id,
            self.timeout_seconds,
        )
        return None

    async def _download_image(
        self,
        session: aiohttp.ClientSession,
        url: str,
    ) -> tuple[bytes, str] | None:
        try:
            async with session.get(
                url,
                headers={"Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.8"},
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "Nexus %s result download failed: HTTP %s",
                        self.model_name,
                        response.status,
                    )
                    return None
                if response.content_length is not None and response.content_length > _MAX_RESULT_BYTES:
                    logger.warning("Nexus %s result exceeds 25 MB", self.model_name)
                    return None
                raw = await response.read()
                if not raw or len(raw) > _MAX_RESULT_BYTES:
                    return None
                return raw, response.headers.get("Content-Type", "image/png").split(";", 1)[0]
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning("Nexus %s result download failure: %s", self.model_name, exc)
            return None

    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
        resolution: str = "4K",
        image_input: list[str] | None = None,
        output_format: str = "png",
    ) -> dict[str, Any] | None:
        if not self.api_key:
            return None

        clean_prompt = str(prompt or "").strip()
        if not clean_prompt:
            # Nexus' published Nano Banana schema requires prompt. Keep image-only
            # legacy requests on the existing Kie fallback instead of sending 422.
            logger.info("Nexus %s skipped: prompt is empty; using fallback", self.model_name)
            return None

        ratio = str(aspect_ratio or "").strip()
        if ratio and ratio.lower() != "auto" and ratio not in _SUPPORTED_ASPECT_RATIOS:
            logger.info(
                "Nexus %s skipped unsupported aspect_ratio=%s; using fallback",
                self.model_name,
                ratio,
            )
            return None

        params = build_nexus_image_params(
            model_name=self.model_name,
            prompt=clean_prompt,
            aspect_ratio=ratio,
            image_input=image_input,
            max_references=self.max_references,
        )
        session = await self._get_session()
        logger.info(
            "Nexus image request: model=%s refs=%s aspect_ratio=%s requested_resolution=%s requested_format=%s",
            self.model_name,
            len(params.get("image_urls") or ([params["image_url"]] if params.get("image_url") else [])),
            params.get("aspect_ratio", "provider_default"),
            resolution,
            output_format,
        )

        task_id = await self._start_task(session, params)
        if not task_id:
            return None
        payload = await self._wait_for_result(session, task_id)
        if not payload:
            return None

        source = _extract_result_source(payload)
        if source is None:
            logger.warning("Nexus %s task %s completed without image result", self.model_name, task_id)
            return None

        source_type, value = source
        try:
            if source_type == "url":
                downloaded = await self._download_image(session, value)
                if downloaded is None:
                    return None
                image_bytes, mime_type = downloaded
            else:
                image_bytes, mime_type = _decode_base64_image(value)
        except (ValueError, TypeError, base64.binascii.Error) as exc:
            logger.warning("Nexus %s returned invalid image data: %s", self.model_name, exc)
            return None

        return {
            "image_bytes": image_bytes,
            "mime_type": mime_type,
            "provider": "nexus",
            "provider_model": self.model_name,
            "provider_task_id": task_id,
            "retryable": False,
        }

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
