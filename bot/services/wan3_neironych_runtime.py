"""Production Wan 3 routing: Neironych native API or compatible legacy KIE.

Provider selection never changes an in-flight task's route: native request IDs
have a distinct prefix, while historical KIE IDs keep their original format.
An uncertain native POST is never retried with a different provider/key.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import aiohttp

from bot.services.neironych_seedance_admin_service import NeironychAPIError
from bot.services.neironych_wan3_admin_service import NeironychWan3AdminService
from bot.services.wan3_prime_media import Wan3PrimeRecipe

logger = logging.getLogger(__name__)

NEIRONYCH_TASK_PREFIX = "neironych:"
_NATIVE_MODEL = {"wan_3": "wan-3", "wan_3_prime": "wan-3-prime"}
_KIE_MODEL = {"wan-3": "wan/3-0-video", "wan-3-prime": "wan/3-0-video-prime"}
_TERMINAL_NATIVE = {"done": "success", "failed": "fail", "expired": "fail"}
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


def native_payload_for_recipe(recipe: Wan3PrimeRecipe) -> dict[str, Any] | None:
    """Return a validated, feature-equivalent native payload or require KIE.

    Never downgrade Prime to Standard, silently discard input controls, or
    change a user-selected aspect ratio to satisfy another provider.
    """
    native_model = _NATIVE_MODEL.get(recipe.model)
    source = recipe.prepared_input
    if not native_model or not source or not recipe.provider_submission_id:
        return None
    if (
        recipe.reference_file_urls or recipe.reference_link_urls or
        recipe.nsfw_checker or source.get("nsfw_checker") is True or
        recipe.duration == -1 or source.get("duration") == -1
    ):
        return None
    if source.get("audio", True) != recipe.audio:
        return None
    # Native edit derives duration/ratio from the input video. KIE accepts
    # explicit output controls, so do not silently drop what the user chose.
    if recipe.scenario in {"file", "link", "edit"}:
        return None
    if recipe.scenario not in {"text", "reference", "first_frame", "first_last", "edit"}:
        return None
    if native_model == "wan-3-prime" and (
        recipe.scenario not in {"text", "reference"} or
        recipe.duration < 4 or
        recipe.aspect_ratio not in {"16:9", "1:1", "9:16"} or
        not recipe.audio or recipe.seed is not None or
        (recipe.reference_audio_urls and not (recipe.reference_image_urls or recipe.reference_video_urls))
    ):
        return None
    if recipe.duration < 2 or recipe.duration > 30:
        return None

    mode = {
        "first_frame": "frames", "first_last": "frames",
    }.get(recipe.scenario, recipe.scenario)
    try:
        body = NeironychWan3AdminService.build_payload(
            mode=mode,
            prompt=str(source.get("prompt") or ""),
            duration=recipe.duration,
            resolution=recipe.resolution.lower(),
            aspect_ratio=recipe.aspect_ratio,
            generate_audio=recipe.audio,
            seed=recipe.seed,
            reference_images=list(recipe.reference_image_urls),
            reference_videos=list(recipe.reference_video_urls),
            reference_audios=list(recipe.reference_audio_urls),
            start_image=recipe.first_frame_url or "",
            end_image=recipe.last_frame_url or "",
        )
    except (TypeError, ValueError):
        return None
    body["model"] = native_model
    # These controls aren't supported by Neironych Prime; fail closed above.
    if native_model == "wan-3-prime":
        body.pop("generate_audio", None)
    return body


def native_download_attempt_budget(*, timeout_seconds: int, deadline: float, now: float) -> float:
    """Keep every retry within the reconciler's task lease."""
    remaining = deadline - now
    if remaining <= 1:
        raise TimeoutError("Wan native download exceeded lease-safe retry budget")
    return min(timeout_seconds, remaining)


class NeironychWan3RuntimeService(NeironychWan3AdminService):
    """Enable both real models; keep admin lab's historic narrow catalog intact."""

    async def list_enabled_wan_models(self) -> set[str]:
        _status, response = await self._request_json(
            method="GET", path="/v1/models", retry=True,
        )
        data = response.get("data")
        if not isinstance(data, list):
            raise NeironychAPIError("Neironych model catalog is invalid")
        return {row["id"] for row in data if isinstance(row, dict) and row.get("id") in _KIE_MODEL}

    async def submit(
        self, payload: dict[str, Any], *, idempotency_key: str,
    ) -> dict[str, Any]:
        key = str(idempotency_key or "").strip()
        if not _SAFE_REQUEST_ID.fullmatch(key) or len(key) < 8:
            raise ValueError("Invalid stable Wan submission ID")
        status, data = await self._request_json(
            method="POST",
            path="/v1/videos/generations",
            headers={
                "Idempotency-Key": key,
                "X-Client-Request-Id": key,
                "X-Submission-Receipt": "v1",
            },
            json_body=payload,
            retry=False,
        )
        request_id = str(data.get("request_id") or "")
        if status not in {200, 202} or not _SAFE_REQUEST_ID.fullmatch(request_id):
            raise NeironychAPIError("Neironych did not confirm request identity", status=status)
        client_id = data.get("client_request_id")
        if client_id is not None and client_id != key:
            raise NeironychAPIError("Neironych returned mismatched client identity", status=status)
        return {"request_id": request_id, "status": "pending"}

    async def lookup_by_client_id(self, internal_task_id: str) -> dict[str, Any] | None:
        if not _SAFE_REQUEST_ID.fullmatch(internal_task_id):
            raise ValueError("Invalid Wan client request identity")
        path_prefix = os.getenv("NEIRONYCH_GENERATIONS_API_PREFIX", "/api/v1").rstrip("/")
        try:
            _status, record = await self._request_json(
                method="GET",
                path=f"{path_prefix}/generations/by-client-request-id/{internal_task_id}",
                retry=True,
            )
        except NeironychAPIError as exc:
            if exc.status == 404:
                # A 404 does not prove the uncertain POST never reached upstream.
                return None
            raise
        return record

    async def download_managed(self, request_id: str, *, task_id: str) -> str:
        """Stream authenticated output with a hard byte cap and atomic rename."""
        if not self.enabled:
            raise RuntimeError("Neironych is not configured")
        if not _SAFE_REQUEST_ID.fullmatch(request_id):
            raise ValueError("Invalid Neironych request_id")
        if not re.fullmatch(r"wan3_[a-f0-9]{32}", task_id):
            raise ValueError("Invalid internal Wan task_id")
        max_bytes = max(1, int(os.getenv("WAN3_RESULT_MAX_BYTES", str(250 * 1024 * 1024))))
        timeout_seconds = max(5, int(os.getenv("WAN3_RESULT_DOWNLOAD_TIMEOUT_SECONDS", "180")))
        # The reconciler holds a lease for download_timeout + 120 seconds.
        # All retries together must finish well before that lease expires,
        # otherwise another worker may open the same temporary path.
        overall_deadline = asyncio.get_running_loop().time() + timeout_seconds + 60
        root = Path("static/uploads/wan3_prime/results")
        root.mkdir(parents=True, exist_ok=True)
        destination = root / (task_id + ".mp4")
        temp = root / (task_id + ".neironych.part")
        try:
            for attempt in range(3):
                total = 0
                try:
                    attempt_timeout = native_download_attempt_budget(
                        timeout_seconds=timeout_seconds,
                        deadline=overall_deadline,
                        now=asyncio.get_running_loop().time(),
                    )
                    timeout = aiohttp.ClientTimeout(total=attempt_timeout)
                    async with (
                        aiohttp.ClientSession(timeout=timeout) as session,
                        session.get(
                            f"{self.base_url}/v1/videos/{request_id}/content",
                            headers={"Authorization": f"Bearer {self.api_key}"},
                        ) as response,
                    ):
                        if response.status >= 400:
                            raise NeironychAPIError(
                                f"Neironych content HTTP {response.status}",
                                status=response.status,
                            )
                        if response.content_length and response.content_length > max_bytes:
                            raise ValueError("Neironych result exceeds byte limit")
                        with temp.open("wb") as out:
                            async for chunk in response.content.iter_chunked(1024 * 1024):
                                total += len(chunk)
                                if total > max_bytes:
                                    raise ValueError("Neironych result exceeds byte limit")
                                await asyncio.to_thread(out.write, chunk)
                    if not total:
                        raise ValueError("Neironych returned empty video content")
                    temp.replace(destination)
                    return str(destination)
                except (NeironychAPIError, aiohttp.ClientError, TimeoutError) as exc:
                    retryable = not isinstance(exc, NeironychAPIError) or (
                        exc.status is not None and 500 <= exc.status < 600
                    )
                    if not retryable or attempt == 2:
                        raise
                    logger.warning(
                        "Wan3 native content retry task=%s attempt=%s error_type=%s",
                        task_id, attempt + 1, type(exc).__name__,
                    )
                    await asyncio.sleep(attempt + 1)
                finally:
                    temp.unlink(missing_ok=True)
            raise RuntimeError("Wan3 content unavailable")
        finally:
            temp.unlink(missing_ok=True)


class Wan3NeironychRuntimeTransport:
    def __init__(
        self,
        *,
        kie: Any,
        neironych: Any | None = None,
        primary_provider: Callable[[], Any] | None = None,
        record_attempt: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self.kie = kie
        self.neironych = neironych or NeironychWan3RuntimeService()
        self.primary_provider = primary_provider or self._configured_provider
        self.record_attempt = record_attempt or self._persist_native_attempt

    @staticmethod
    async def _persist_native_attempt(internal_task_id: str) -> None:
        """Durably record the selected provider before the first paid POST."""
        from bot import database
        from bot import db as db_backend

        database_path = str(getattr(database, "DATABASE_PATH", None) or
                            os.getenv("DATABASE_PATH") or "bot.db")
        async with db_backend.connect(database_path) as db:
            db.row_factory = db_backend.Row
            cursor = await db.execute(
                "SELECT request_data FROM generation_tasks WHERE task_id = ?",
                (internal_task_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("Wan generation task was not persisted before submission")
            raw_metadata = row["request_data"]
            metadata = raw_metadata if isinstance(raw_metadata, dict) else json.loads(raw_metadata or "{}")
            if not isinstance(metadata, dict):
                raise TypeError("Wan generation task metadata is malformed")
            metadata["provider_submission_route"] = "neironych"
            metadata["provider"] = "neironych"
            updated = await db.execute(
                "UPDATE generation_tasks SET request_data = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE task_id = ? AND status = 'processing'",
                (json.dumps(metadata, ensure_ascii=False, sort_keys=True), internal_task_id),
            )
            if updated.rowcount != 1:
                raise RuntimeError("Wan submission route persistence could not be confirmed")
            await db.commit()

    @staticmethod
    async def _configured_provider() -> str:
        from bot.database import get_bot_setting

        default = os.getenv("WAN3_PRIMARY_PROVIDER", "neironych")
        return str(await get_bot_setting("wan3_primary_provider", default)).strip().lower()

    async def create_task(self, recipe: Wan3PrimeRecipe, *, callback_url: str | None) -> dict[str, Any]:
        provider = self.primary_provider()
        if inspect.isawaitable(provider):
            provider = await provider
        payload = native_payload_for_recipe(recipe) if provider == "neironych" else None
        if payload and self.neironych.enabled:
            try:
                models = await self.neironych.list_enabled_wan_models()
            except (NeironychAPIError, aiohttp.ClientError, TimeoutError) as exc:
                logger.warning("Wan3 native catalog unavailable error_type=%s", type(exc).__name__)
                models = set()
            if payload["model"] in models:
                # Commit the native route before the paid POST. A lost receipt
                # can then be looked up by the stable X-Client-Request-Id.
                try:
                    await self.record_attempt(recipe.provider_submission_id)
                except Exception as exc:  # noqa: BLE001 - no paid provider call has started
                    logger.error(
                        "Wan3 native submission preflight persistence failed task=%s error_type=%s",
                        recipe.provider_submission_id, type(exc).__name__,
                    )
                    return {
                        "success": False,
                        "error": "api_error",
                        "status_code": 503,
                        "definitive_pre_submission_failure": True,
                        "message": "Provider route persistence failed before submission",
                    }
                # Never catch an uncertain POST and start a second paid KIE job.
                try:
                    result = await self.neironych.submit(
                        payload, idempotency_key=recipe.provider_submission_id,
                    )
                except NeironychAPIError as exc:
                    # Explicit provider rejection: no task was accepted, so the
                    # existing Wan lifecycle can refund the reserved credits.
                    if exc.status in {400, 401, 402, 403, 404, 422}:
                        return {
                            "success": False,
                            "error": "api_error",
                            "status_code": exc.status,
                            "message": "Neironych rejected the generation request",
                        }
                    # 429/5xx may arrive after acceptance at an upstream
                    # gateway: never start a second paid KIE request.
                    raise
                request_id = str(result["request_id"])
                if not _SAFE_REQUEST_ID.fullmatch(request_id):
                    raise RuntimeError("Invalid Neironych acceptance identifier")
                logger.info("Wan3 submitted provider=neironych model=%s", payload["model"])
                return {"task_id": NEIRONYCH_TASK_PREFIX + request_id}
        logger.info("Wan3 submitted route=kie model=%s reason=primary_or_compatibility", recipe.model)
        return await self.kie.create_task(recipe, callback_url=callback_url)

    async def get_task_status(self, provider_task_id: str) -> dict[str, Any] | None:
        if not provider_task_id.startswith(NEIRONYCH_TASK_PREFIX):
            return await self.kie.get_task_status(provider_task_id)
        request_id = provider_task_id[len(NEIRONYCH_TASK_PREFIX):]
        if not _SAFE_REQUEST_ID.fullmatch(request_id):
            raise ValueError("Invalid Neironych task identity")
        record = await self.neironych.get_status(request_id)
        state = str(record.get("status") or "").lower()
        native_model = str(record.get("model") or "")
        result: dict[str, Any] = {
            "taskId": provider_task_id,
            "state": _TERMINAL_NATIVE.get(state, "processing"),
        }
        if native_model in _KIE_MODEL:
            result["model"] = _KIE_MODEL[native_model]
        result["source"] = "neironych"
        if record.get("client_request_id"):
            result["client_request_id"] = record["client_request_id"]
        if state == "done":
            # Marker is never passed to the public downloader.
            result["resultUrls"] = [provider_task_id]
        elif state in {"failed", "expired"}:
            result["failCode"] = state
            result["failMsg"] = str(record.get("error") or state)[:300]
        return result

    async def lookup_native_submission(self, internal_task_id: str) -> dict[str, Any] | None:
        return await self.neironych.lookup_by_client_id(internal_task_id)

    async def download_result(self, provider_task_id: str, *, task_id: str) -> str:
        if not provider_task_id.startswith(NEIRONYCH_TASK_PREFIX):
            raise ValueError("Not a native Neironych task")
        request_id = provider_task_id[len(NEIRONYCH_TASK_PREFIX):]
        return await self.neironych.download_managed(request_id, task_id=task_id)

    async def close(self) -> None:
        await self.kie.close()
