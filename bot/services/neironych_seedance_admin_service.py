from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlparse

import aiohttp


class NeironychAPIError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class SeedanceModelSpec:
    duration_range: tuple[int, int]
    resolutions: tuple[str, ...]
    max_images: int
    max_videos: int
    max_audios: int
    max_references: int
    supports_edit: bool = False


class NeironychSeedanceAdminService:
    API_BASE = "https://api.xn--e1aikcel5c5a.online"
    FIXED_RATIOS = ("1:1", "16:9", "9:16", "4:3", "3:4", "21:9")
    MAX_PROMPT_BYTES = 40_000
    REFERENCE_RE = re.compile(r"@(Image|Video|Audio)\s*(\d+)", flags=re.IGNORECASE)
    MODEL_SPECS: ClassVar[dict[str, SeedanceModelSpec]] = {
        "seedance-2.5": SeedanceModelSpec(
            duration_range=(4, 30),
            resolutions=("480p", "720p", "1080p"),
            max_images=30,
            max_videos=10,
            max_audios=10,
            max_references=50,
            supports_edit=True,
        ),
        "seedance-2.0": SeedanceModelSpec(
            duration_range=(4, 15),
            resolutions=("480p", "720p", "1080p", "4k"),
            max_images=9,
            max_videos=3,
            max_audios=3,
            max_references=12,
        ),
        "seedance-2.0-mini": SeedanceModelSpec(
            duration_range=(4, 15),
            resolutions=("480p", "720p"),
            max_images=9,
            max_videos=3,
            max_audios=3,
            max_references=12,
        ),
        "seedance-2.0-fast": SeedanceModelSpec(
            duration_range=(4, 15),
            resolutions=("480p", "720p"),
            max_images=9,
            max_videos=3,
            max_audios=3,
            max_references=12,
        ),
    }

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self.api_key = (
            api_key
            if api_key is not None
            else os.getenv("NEIRONYCH_API_KEY", "")
        ).strip()
        self.base_url = (
            base_url
            if base_url is not None
            else os.getenv("NEIRONYCH_API_BASE_URL", self.API_BASE)
        ).rstrip("/")
        env_timeout = os.getenv("NEIRONYCH_HTTP_TIMEOUT_SECONDS", "")
        effective_timeout = timeout_seconds if not env_timeout else int(float(env_timeout))
        self.timeout_seconds = max(15, int(effective_timeout))
        self.poll_interval_seconds = max(
            1.0,
            float(os.getenv("NEIRONYCH_TEST_POLL_INTERVAL_SECONDS", "10")),
        )
        self.poll_timeout_seconds = max(
            60.0,
            float(os.getenv("NEIRONYCH_TEST_POLL_TIMEOUT_SECONDS", "1800")),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.base_url)

    @classmethod
    def spec(cls, model: str) -> SeedanceModelSpec:
        try:
            return cls.MODEL_SPECS[model]
        except KeyError as exc:
            raise ValueError(f"Unsupported Seedance model: {model}") from exc

    @staticmethod
    def _normalize_urls(values: list[str] | None, field: str) -> list[str]:
        result: list[str] = []
        for raw in values or []:
            value = str(raw or "").strip()
            if not value:
                continue
            parsed = urlparse(value)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError(f"{field} must contain public HTTPS URLs")
            if parsed.username or parsed.password:
                raise ValueError(f"{field} must not contain URL credentials")
            if value not in result:
                result.append(value)
        return result

    @classmethod
    def _validate_prompt_references(
        cls,
        prompt: str,
        *,
        images: int,
        videos: int,
        audios: int,
    ) -> None:
        required = {"image": 0, "video": 0, "audio": 0}
        for kind, raw_index in cls.REFERENCE_RE.findall(prompt):
            key = kind.lower()
            required[key] = max(required[key], int(raw_index))
        available = {"image": images, "video": videos, "audio": audios}
        missing = [
            f"@{kind.title()}{required_count}"
            for kind, required_count in required.items()
            if required_count > available[kind]
        ]
        if missing:
            raise ValueError(
                "prompt references missing media: " + ", ".join(missing)
            )

    @classmethod
    def build_payload(
        cls,
        *,
        model: str,
        mode: str,
        prompt: str,
        duration: int,
        resolution: str,
        aspect_ratio: str,
        reference_images: list[str] | None = None,
        reference_videos: list[str] | None = None,
        reference_audios: list[str] | None = None,
        start_image: str = "",
        end_image: str = "",
    ) -> dict[str, Any]:
        spec = cls.spec(model)
        mode = str(mode or "text").strip().lower()
        if mode not in {"text", "reference", "frames", "edit"}:
            raise ValueError(f"Unsupported Seedance mode: {mode}")

        prompt = str(prompt or "").strip()
        if not prompt:
            raise ValueError("prompt is required")
        if len(prompt.encode("utf-8")) > cls.MAX_PROMPT_BYTES:
            raise ValueError("prompt exceeds 40 000 UTF-8 bytes")

        resolution = str(resolution or "").strip()
        if resolution not in spec.resolutions:
            raise ValueError(
                f"resolution {resolution!r} is not supported by {model}"
            )

        images = cls._normalize_urls(reference_images, "reference_images")
        videos = cls._normalize_urls(reference_videos, "reference_videos")
        audios = cls._normalize_urls(reference_audios, "reference_audios")
        start = cls._normalize_urls([start_image] if start_image else [], "start_image")
        end = cls._normalize_urls([end_image] if end_image else [], "end_image")
        start_url = start[0] if start else ""
        end_url = end[0] if end else ""

        if len(images) > spec.max_images:
            raise ValueError(f"{model} accepts at most {spec.max_images} image references")
        if len(videos) > spec.max_videos:
            raise ValueError(f"{model} accepts at most {spec.max_videos} video references")
        if len(audios) > spec.max_audios:
            raise ValueError(f"{model} accepts at most {spec.max_audios} audio references")
        if len(images) + len(videos) + len(audios) > spec.max_references:
            raise ValueError(f"{model} accepts at most {spec.max_references} total references")

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "resolution": resolution,
        }

        if mode == "edit":
            if not spec.supports_edit:
                raise ValueError("edit mode is supported only by seedance-2.5")
            if start_url or end_url:
                raise ValueError("Seedance 2.5 edit cannot be combined with frame mode")
            if not videos:
                raise ValueError("Seedance 2.5 edit requires reference_videos")
            payload.update(
                {
                    "duration": -1,
                    "aspect_ratio": "adaptive",
                    "reference_videos": [{"url": url} for url in videos],
                    "omni_reference_task_type": "edit",
                }
            )
            if images:
                payload["reference_images"] = [{"url": url} for url in images]
            if audios:
                payload["reference_audios"] = [{"url": url} for url in audios]
            cls._validate_prompt_references(
                prompt,
                images=len(images),
                videos=len(videos),
                audios=len(audios),
            )
            return payload

        minimum, maximum = spec.duration_range
        if not isinstance(duration, int) or not minimum <= duration <= maximum:
            raise ValueError(
                f"duration for {model} must be between {minimum} and {maximum} seconds"
            )
        payload["duration"] = duration

        if mode == "frames":
            if images or videos or audios:
                raise ValueError("frame mode cannot be combined with reference_*")
            if not start_url:
                raise ValueError("frames mode requires start_image")
            if model == "seedance-2.5":
                if aspect_ratio != "adaptive":
                    raise ValueError("Seedance 2.5 frame mode requires adaptive aspect_ratio")
                payload["aspect_ratio"] = "adaptive"
            else:
                if aspect_ratio not in cls.FIXED_RATIOS:
                    raise ValueError("Seedance 2.0 frame mode requires a fixed aspect_ratio")
                payload["aspect_ratio"] = aspect_ratio
            payload["start_image"] = {"url": start_url}
            if end_url:
                payload["end_image"] = {"url": end_url}
            cls._validate_prompt_references(prompt, images=0, videos=0, audios=0)
            return payload

        if start_url or end_url:
            raise ValueError("start_image/end_image require frames mode")
        if aspect_ratio not in cls.FIXED_RATIOS:
            raise ValueError("text/reference mode requires a fixed aspect_ratio")
        payload["aspect_ratio"] = aspect_ratio

        if mode == "text":
            if images or videos or audios:
                raise ValueError("text mode cannot include references")
            cls._validate_prompt_references(prompt, images=0, videos=0, audios=0)
            return payload

        if not (images or videos or audios):
            raise ValueError("reference mode requires at least one reference")
        if model != "seedance-2.5" and audios and not (images or videos):
            raise ValueError("Seedance 2.0 audio requires an image or video reference")

        if images:
            payload["reference_images"] = [{"url": url} for url in images]
        if videos:
            payload["reference_videos"] = [{"url": url} for url in videos]
        if audios:
            payload["reference_audios"] = [{"url": url} for url in audios]
        if model == "seedance-2.5":
            payload["omni_reference_task_type"] = "reference"
        cls._validate_prompt_references(
            prompt,
            images=len(images),
            videos=len(videos),
            audios=len(audios),
        )
        return payload

    async def _request_json(
        self,
        *,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        retry: bool = True,
    ) -> tuple[int, dict[str, Any]]:
        request_headers = {"Accept": "application/json"}
        if path != "/v1/models":
            if not self.api_key:
                raise RuntimeError("NEIRONYCH_API_KEY is not configured")
            request_headers["Authorization"] = f"Bearer {self.api_key}"
        if json_body is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})

        attempts = 2 if retry and method.upper() == "GET" else 1
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        last_error: Exception | None = None
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in range(attempts):
                try:
                    async with session.request(
                        method.upper(),
                        f"{self.base_url}{path}",
                        headers=request_headers,
                        json=json_body,
                    ) as response:
                        raw = await response.text()
                        try:
                            data = json.loads(raw) if raw else {}
                        except json.JSONDecodeError:
                            data = {"detail": raw[:1000]}
                        if response.status >= 400:
                            detail = data.get("detail") or data.get("error") or data
                            raise NeironychAPIError(
                                f"Neironych API HTTP {response.status}: {detail}",
                                status=response.status,
                            )
                        if not isinstance(data, dict):
                            raise NeironychAPIError("Neironych API returned non-object JSON")
                        return response.status, data
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    last_error = exc
                    if attempt + 1 >= attempts:
                        raise
                    await asyncio.sleep(1)
        raise RuntimeError("Neironych API request failed") from last_error

    async def list_enabled_seedance_models(self) -> set[str]:
        _status, data = await self._request_json(
            method="GET",
            path="/v1/models",
            retry=True,
        )
        result: set[str] = set()
        for item in data.get("data") or []:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "").strip()
            if model_id in self.MODEL_SPECS:
                result.add(model_id)
        return result

    async def submit(
        self,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        key = str(idempotency_key or "").strip()
        if len(key) < 8:
            raise ValueError("idempotency_key must be at least 8 characters")
        status, data = await self._request_json(
            method="POST",
            path="/v1/videos/generations",
            headers={"Idempotency-Key": key},
            json_body=payload,
            retry=False,
        )
        request_id = str(data.get("request_id") or "").strip()
        if status not in {200, 202} or not request_id:
            raise NeironychAPIError("Neironych API did not return request_id", status=status)
        return {"request_id": request_id, "status": "pending"}

    async def get_status(self, request_id: str) -> dict[str, Any]:
        _status, data = await self._request_json(
            method="GET",
            path=f"/v1/videos/{request_id}",
            retry=True,
        )
        return data

    async def wait_for_result(
        self,
        request_id: str,
        *,
        poll_seconds: float | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        effective_poll = self.poll_interval_seconds if poll_seconds is None else poll_seconds
        effective_timeout = (
            self.poll_timeout_seconds if timeout_seconds is None else timeout_seconds
        )
        deadline = asyncio.get_running_loop().time() + effective_timeout
        while True:
            record = await self.get_status(request_id)
            state = str(record.get("status") or "").lower()
            if state in {"done", "failed", "expired"}:
                return record
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(
                    "Seedance is still pending; keep the same request_id and check later"
                )
            await asyncio.sleep(max(0.1, effective_poll))

    async def download_to_temp(self, request_id: str) -> str:
        if not self.api_key:
            raise RuntimeError("NEIRONYCH_API_KEY is not configured")
        timeout = aiohttp.ClientTimeout(total=max(self.timeout_seconds, 300))
        safe_request_id = "".join(
            char for char in str(request_id)[:24] if char.isalnum() or char in {"-", "_"}
        ) or "request"
        fd, path = tempfile.mkstemp(
            prefix=f"seedance-admin-{safe_request_id}-",
            suffix=".mp4",
        )
        try:
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.get(
                    f"{self.base_url}/v1/videos/{request_id}/content",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                ) as response,
            ):
                if response.status >= 400:
                    text = await response.text()
                    raise NeironychAPIError(
                        f"Neironych content HTTP {response.status}: {text[:500]}",
                        status=response.status,
                    )
                async for chunk in response.content.iter_chunked(1024 * 1024):
                    await asyncio.to_thread(os.write, fd, chunk)
            await asyncio.to_thread(os.fsync, fd)
            os.close(fd)
            fd = -1
            return path
        except Exception:
            if fd >= 0:
                os.close(fd)
            Path(path).unlink(missing_ok=True)
            raise


neironych_seedance_admin_service = NeironychSeedanceAdminService()
