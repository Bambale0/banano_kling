"""Neironych transport for the shared Wan 3 lifecycle."""

from __future__ import annotations

import json
import os
import uuid
from copy import deepcopy
from typing import Any, ClassVar

import aiohttp

from bot.services.wan3_models import wan3_model_spec


class NeironychWan3Error(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class NeironychWan3Unsupported(ValueError):
    """The frozen KIE-compatible recipe cannot be represented by Neironych."""


class NeironychWan3Service:
    API_BASE = "https://api.xn--e1aikcel5c5a.online"
    PROVIDER_PREFIX = "neironych:"
    MODEL_IDS: ClassVar[dict[str, str]] = {
        "wan_3": "wan-3",
        "wan_3_prime": "wan-3-prime",
    }
    PRIME_RATIOS: ClassVar[set[str]] = {"16:9", "1:1", "9:16"}

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self.api_key = (
            api_key if api_key is not None else os.getenv("NEIRONYCH_API_KEY", "")
        ).strip()
        self.base_url = (
            base_url
            if base_url is not None
            else os.getenv("NEIRONYCH_API_BASE_URL", self.API_BASE)
        ).rstrip("/")
        configured_timeout = os.getenv("NEIRONYCH_HTTP_TIMEOUT_SECONDS", "")
        self.timeout_seconds = max(
            15,
            int(float(configured_timeout)) if configured_timeout else timeout_seconds,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.base_url)

    @classmethod
    def owns(cls, provider_task_id: str) -> bool:
        return str(provider_task_id or "").startswith(cls.PROVIDER_PREFIX)

    @staticmethod
    def _reference_objects(values: Any) -> list[dict[str, str]]:
        return [
            {"url": str(value)}
            for value in values or []
            if isinstance(value, str) and value.strip()
        ]

    @classmethod
    def build_payload(cls, recipe: Any) -> dict[str, Any]:
        """Translate the server-frozen Wan recipe to the Neironych contract."""
        prepared = deepcopy(recipe.prepared_input)
        if not isinstance(prepared, dict):
            raise NeironychWan3Unsupported("Wan 3 provider input is missing")
        if prepared.get("reference_file_urls") or prepared.get("reference_link_urls"):
            raise NeironychWan3Unsupported(
                "Neironych Wan 3 does not accept file or link references"
            )
        if prepared.get("nsfw_checker") is True:
            raise NeironychWan3Unsupported(
                "Neironych Wan 3 does not expose the KIE NSFW switch"
            )

        model_key = wan3_model_spec(recipe.model).key
        scenario = str(recipe.scenario or "text")
        duration = prepared.get("duration")
        ratio = str(prepared.get("aspect_ratio") or "adaptive")
        audio = prepared.get("audio", True)
        seed = prepared.get("seed")
        if model_key == "wan_3_prime":
            if scenario in {"first_frame", "first_last", "edit"}:
                raise NeironychWan3Unsupported(
                    "Neironych Wan 3 Prime does not support frames or edit"
                )
            if duration not in range(4, 31):
                raise NeironychWan3Unsupported(
                    "Neironych Wan 3 Prime supports 4-30 seconds"
                )
            if ratio not in cls.PRIME_RATIOS:
                raise NeironychWan3Unsupported(
                    "Neironych Wan 3 Prime supports 16:9, 1:1 and 9:16"
                )
            if seed is not None or audio is False:
                raise NeironychWan3Unsupported(
                    "Neironych Wan 3 Prime does not support seed or muted output"
                )

        payload: dict[str, Any] = {
            "model": cls.MODEL_IDS[model_key],
            "prompt": str(prepared.get("prompt") or ""),
            "resolution": str(prepared.get("resolution") or "720P").lower(),
        }
        if scenario != "edit" and duration != -1:
            payload["duration"] = duration
        if (
            scenario not in {"edit", "first_frame", "first_last"}
            and ratio != "adaptive"
        ):
            payload["aspect_ratio"] = ratio
        if scenario == "edit":
            payload["omni_reference_task_type"] = "edit"
        if audio is False:
            payload["generate_audio"] = False
        if seed is not None:
            payload["seed"] = seed

        for source, target in (
            ("reference_image_urls", "reference_images"),
            ("reference_video_urls", "reference_videos"),
            ("reference_audio_urls", "reference_audios"),
        ):
            references = cls._reference_objects(prepared.get(source))
            if references:
                payload[target] = references
        first = str(prepared.get("first_frame_url") or "").strip()
        last = str(prepared.get("last_frame_url") or "").strip()
        if first:
            payload["start_image"] = {"url": first}
        if last:
            payload["end_image"] = {"url": last}
        return payload

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        if not self.enabled:
            raise RuntimeError("NEIRONYCH_API_KEY is not configured")
        request_headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        async with (
            aiohttp.ClientSession(timeout=timeout) as session,
            session.request(
                method,
                f"{self.base_url}{path}",
                headers=request_headers,
                json=body,
            ) as response,
        ):
            raw = await response.text()
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {"detail": raw[:1000]}
            if response.status >= 400:
                detail = data.get("detail") or data.get("error") or data
                raise NeironychWan3Error(
                    f"Neironych API HTTP {response.status}: {detail}",
                    status=response.status,
                )
            if not isinstance(data, dict):
                raise NeironychWan3Error("Neironych API returned non-object JSON")
            return response.status, data

    @staticmethod
    def _client_uuid(idempotency_key: str) -> str:
        value = str(idempotency_key or "")
        if value.startswith("wan3_"):
            try:
                return str(uuid.UUID(hex=value.removeprefix("wan3_")))
            except ValueError:
                pass
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "banano-wan3:" + value))

    async def _recover(self, client_uuid: str) -> str | None:
        try:
            _status, data = await self._request_json(
                "GET", f"/api/v1/generations/by-client-request-id/{client_uuid}"
            )
        except NeironychWan3Error as exc:
            if exc.status == 404:
                return None
            raise
        request_id = str(data.get("request_id") or data.get("id") or "").strip()
        return request_id or None

    async def create_task(self, recipe: Any, *, idempotency_key: str) -> dict[str, Any]:
        payload = self.build_payload(recipe)
        client_uuid = self._client_uuid(idempotency_key)
        headers = {
            "Idempotency-Key": f"generation:{client_uuid}:provider:1",
            "X-Client-Request-Id": client_uuid,
        }
        try:
            status, data = await self._request_json(
                "POST", "/v1/videos/generations", headers=headers, body=payload
            )
        except (aiohttp.ClientError, TimeoutError):
            recovered = await self._recover(client_uuid)
            if recovered:
                return {
                    "success": True,
                    "task_id": self.PROVIDER_PREFIX + recovered,
                    "provider": "neironych",
                }
            raise
        except NeironychWan3Error as exc:
            if exc.status is not None and exc.status < 500:
                raise
            recovered = await self._recover(client_uuid)
            if recovered:
                return {
                    "success": True,
                    "task_id": self.PROVIDER_PREFIX + recovered,
                    "provider": "neironych",
                }
            raise
        request_id = str(data.get("request_id") or "").strip()
        if status not in {200, 202} or not request_id:
            recovered = await self._recover(client_uuid)
            if recovered:
                return {
                    "success": True,
                    "task_id": self.PROVIDER_PREFIX + recovered,
                    "provider": "neironych",
                }
            raise NeironychWan3Error(
                "Neironych API did not return request_id", status=status
            )
        return {
            "success": True,
            "task_id": self.PROVIDER_PREFIX + request_id,
            "provider": "neironych",
        }

    async def get_task_status(self, provider_task_id: str) -> dict[str, Any]:
        request_id = str(provider_task_id).removeprefix(self.PROVIDER_PREFIX)
        _status, data = await self._request_json("GET", f"/v1/videos/{request_id}")
        state = str(data.get("status") or "unknown").lower()
        normalized_state = {
            "done": "success",
            "failed": "fail",
            "expired": "fail",
        }.get(state, state)
        model_id = str(data.get("model") or "")
        internal_model = {
            "wan-3": "wan/3-0-video",
            "wan-3-prime": "wan/3-0-video-prime",
        }.get(model_id)
        if internal_model is None:
            # The status contract may omit model; the lifecycle still verifies
            # task ownership by its namespaced provider ID.
            internal_model = None
        video = data.get("video") if isinstance(data.get("video"), dict) else {}
        video_url = str(video.get("url") or "").strip()
        result: dict[str, Any] = {
            "taskId": self.PROVIDER_PREFIX + request_id,
            "state": normalized_state,
        }
        if internal_model:
            result["model"] = internal_model
        if video_url:
            result["response"] = {"resultUrls": [video_url]}
        if normalized_state == "fail":
            error = data.get("error")
            result["failCode"] = state
            result["failMsg"] = (
                str(error.get("message") or error.get("detail") or error)
                if isinstance(error, dict)
                else str(error or state)
            )
        return result


neironych_wan3_service = NeironychWan3Service()
