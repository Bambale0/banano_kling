from __future__ import annotations

import asyncio
import json
import mimetypes
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from uuid import uuid4

import aiohttp

from bot.services.media_input_utils import resolve_local_upload_path

DEFAULT_RENDERGRID_BASE_URL = "https://api.rendergrid.io/api/public/v1"
MIN_CREATION_POLL_INTERVAL_SECONDS = 5.0
TERMINAL_CREATION_STATUSES = frozenset({"completed", "failed"})
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
REFERENCE_IDENTITY_MARKER = "[REFERENCE IDENTITY LOCK]"
REFERENCE_IDENTITY_INSTRUCTION = (
    f"{REFERENCE_IDENTITY_MARKER}\n"
    "Use the provided reference image as the source of truth for the referenced subject. "
    "If the reference contains a person, preserve the exact same person's identity: facial "
    "structure, proportions, age, skin tone, hair, and distinctive features. Do not replace "
    "the person with a lookalike or a newly invented face. Apply the user's requested changes "
    "to that same subject. If the reference contains an object or product, preserve its "
    "identity, shape, proportions, materials, markings, and distinctive details."
)


@dataclass(slots=True)
class RenderGridError(RuntimeError):
    message: str
    status: int | None = None
    code: str | None = None
    payload: Any = None
    retry_after: float | None = None

    def __str__(self) -> str:
        return self.message


class RenderGridClient:
    """Async client for RenderGrid's public v1 API.

    RenderGrid generation is asynchronous: ``generate_image`` returns a creation
    id immediately and ``get_creation``/``wait_for_creation`` resolve the final
    result. The API key never belongs in browser code.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int = 2,
    ) -> None:
        self.api_key = (api_key or os.getenv("RENDERGRID_API_KEY", "")).strip()
        self.base_url = (
            base_url
            or os.getenv("RENDERGRID_BASE_URL", "")
            or DEFAULT_RENDERGRID_BASE_URL
        ).rstrip("/")
        self.timeout_seconds = float(
            timeout_seconds
            if timeout_seconds is not None
            else os.getenv("RENDERGRID_TIMEOUT_SECONDS", "60")
        )
        self.max_retries = max(0, int(max_retries))

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        if not self.api_key:
            raise RenderGridError("RENDERGRID_API_KEY is not configured")
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
            nested = payload.get("error")
            if isinstance(nested, Mapping):
                message = str(
                    nested.get("message")
                    or nested.get("detail")
                    or payload.get("message")
                    or f"RenderGrid request failed ({status})"
                )
                code = nested.get("code") or payload.get("code")
                return message, str(code) if code is not None else None
            if isinstance(nested, str) and nested.strip():
                return nested.strip(), str(payload.get("code") or "") or None
            message = str(
                payload.get("message")
                or payload.get("detail")
                or f"RenderGrid request failed ({status})"
            )
            code = payload.get("code")
            return message, str(code) if code is not None else None
        return f"RenderGrid request failed ({status})", None

    @staticmethod
    def _retry_after_seconds(
        response: aiohttp.ClientResponse,
        attempt: int,
    ) -> float:
        raw = response.headers.get("Retry-After", "").strip()
        if raw:
            try:
                return max(0.0, min(float(raw), 30.0))
            except ValueError:
                pass
        return min(2.0**attempt, 8.0)

    @staticmethod
    def _normalize_reference_images(value: Any) -> list[str]:
        if value in (None, "", []):
            return []
        if isinstance(value, str):
            raw_items: Sequence[Any] = [value]
        elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
            raw_items = value
        else:
            raise TypeError("RenderGrid reference_images must be a list of public image URLs")

        normalized: list[str] = []
        seen: set[str] = set()
        for raw in raw_items:
            url = str(raw or "").strip()
            if not url:
                continue
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(
                    "RenderGrid reference image must be available through a public HTTP(S) URL"
                )
            if url not in seen:
                seen.add(url)
                normalized.append(url)
        if raw_items and not normalized:
            raise ValueError("RenderGrid reference_images is empty")
        return normalized

    @classmethod
    def _prepare_generation_payload(cls, payload: Mapping[str, Any]) -> dict[str, Any]:
        prepared = dict(payload)
        prompt = str(prepared.get("prompt") or "").strip()
        references = cls._normalize_reference_images(
            prepared.get("image_urls")
            if prepared.get("image_urls") is not None
            else prepared.get("reference_images")
        )
        if references:
            prepared["image_urls"] = references
            prepared.pop("reference_images", None)
            if REFERENCE_IDENTITY_MARKER not in prompt:
                prepared["prompt"] = f"{REFERENCE_IDENTITY_INSTRUCTION}\n\nUser request:\n{prompt}"
        else:
            prepared.pop("image_urls", None)
            prepared.pop("reference_images", None)
        return prepared

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        last_error: RenderGridError | None = None

        async with aiohttp.ClientSession(timeout=timeout) as session:
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
                        last_error = RenderGridError(
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
                except RenderGridError:
                    raise
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    last_error = RenderGridError(
                        message=f"RenderGrid network error: {exc}",
                        payload={"exception": type(exc).__name__},
                    )
                    if attempt >= self.max_retries:
                        raise last_error from exc
                    await asyncio.sleep(min(2.0**attempt, 8.0))

        if last_error is not None:
            raise last_error
        raise RenderGridError("RenderGrid request failed")

    async def _upload_local_reference(self, source: str) -> str | None:
        local_path = resolve_local_upload_path(source)
        if not local_path:
            return None

        try:
            file_bytes = await asyncio.to_thread(Path(local_path).read_bytes)
            filename = os.path.basename(local_path) or "reference.png"
            content_type = mimetypes.guess_type(filename)[0] or "image/png"
            form = aiohttp.FormData()
            form.add_field(
                "file",
                file_bytes,
                filename=filename,
                content_type=content_type,
            )
            form.add_field("kind", "image")
            timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.post(
                    f"{self.base_url}/uploads",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Accept": "application/json",
                    },
                    data=form,
                ) as response,
            ):
                raw = await response.text()
                payload = self._decode_payload(raw)
                if response.status < 200 or response.status >= 300:
                    message, code = self._error_details(payload, response.status)
                    raise RenderGridError(message, response.status, code, payload)
                file_id = payload.get("file_id") if isinstance(payload, dict) else None
                if not file_id:
                    raise RenderGridError(
                        "RenderGrid upload returned no file_id",
                        payload=payload,
                    )
                return str(file_id)
        except RenderGridError:
            raise
        except (OSError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise RenderGridError(
                f"RenderGrid reference upload failed: {type(exc).__name__}",
                payload={"exception": type(exc).__name__},
            ) from exc

    async def generate_image(
        self,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        model = str(payload.get("model") or "").strip()
        prompt = str(payload.get("prompt") or "").strip()
        if not model:
            raise ValueError("RenderGrid model is required")
        if not prompt:
            raise ValueError("RenderGrid prompt is required")

        prepared_payload = self._prepare_generation_payload(payload)
        image_urls = prepared_payload.pop("image_urls", None)
        if image_urls:
            local_file_ids = [
                file_id
                for image_url in image_urls
                if (file_id := await self._upload_local_reference(image_url))
            ]
            if local_file_ids:
                if len(local_file_ids) != len(image_urls):
                    raise RenderGridError(
                        "RenderGrid references must be all local uploads or all public URLs"
                    )
                prepared_payload["image_file_ids"] = local_file_ids
            else:
                prepared_payload["image_urls"] = image_urls
        key = (idempotency_key or str(uuid4())).strip()
        result = await self._request(
            "POST",
            "/images/generate",
            json_body=prepared_payload,
            idempotency_key=key,
        )
        if not isinstance(result, dict):
            raise RenderGridError(
                "RenderGrid returned an invalid generation response",
                payload=result,
            )
        return result

    async def get_creation(self, creation_id: str) -> dict[str, Any]:
        creation_id = str(creation_id or "").strip()
        if not creation_id:
            raise ValueError("creation_id is required")
        encoded_creation_id = quote(creation_id, safe="")
        result = await self._request("GET", f"/creations/{encoded_creation_id}")
        if not isinstance(result, dict):
            raise RenderGridError(
                "RenderGrid returned an invalid creation response",
                payload=result,
            )
        return result

    async def list_models(self) -> Any:
        return await self._request("GET", "/models")

    async def get_balance(self) -> Any:
        return await self._request("GET", "/balance")

    async def wait_for_creation(
        self,
        creation_id: str,
        *,
        timeout_seconds: float = 600.0,
        poll_interval_seconds: float = MIN_CREATION_POLL_INTERVAL_SECONDS,
    ) -> dict[str, Any]:
        poll_interval = max(
            MIN_CREATION_POLL_INTERVAL_SECONDS,
            float(poll_interval_seconds),
        )
        deadline = asyncio.get_running_loop().time() + max(
            0.0,
            float(timeout_seconds),
        )

        while True:
            creation = await self.get_creation(creation_id)
            status = str(creation.get("status") or "").strip().lower()
            if status in TERMINAL_CREATION_STATUSES:
                return creation
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(
                    f"RenderGrid creation {creation_id} did not finish in time"
                )
            await asyncio.sleep(poll_interval)


rendergrid_client = RenderGridClient()
