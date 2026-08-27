from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import aiohttp


DEFAULT_RENDERGRID_BASE_URL = "https://api.rendergrid.io/api/public/v1"
MIN_CREATION_POLL_INTERVAL_SECONDS = 5.0
TERMINAL_CREATION_STATUSES = frozenset({"completed", "failed"})
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


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

        key = (idempotency_key or str(uuid.uuid4())).strip()
        result = await self._request(
            "POST",
            "/images/generate",
            json_body=payload,
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
        result = await self._request("GET", f"/creations/{creation_id}")
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
