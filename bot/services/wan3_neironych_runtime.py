"""Production Wan 3 routing: Neironych native API or compatible legacy KIE.

Provider selection never changes an in-flight task's route: native request IDs
have a distinct prefix, while historical KIE IDs keep their original format.
An uncertain native POST is never retried with a different provider/key.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable

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
    if recipe.scenario in {"file", "link"}:
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
        root = Path("static/uploads/wan3_prime/results")
        root.mkdir(parents=True, exist_ok=True)
        destination = root / (task_id + ".mp4")
        temp = root / (task_id + ".neironych.part")
        try:
            for attempt in range(3):
                total = 0
                try:
                    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.get(
                            f"{self.base_url}/v1/videos/{request_id}/content",
                            headers={"Authorization": f"Bearer {self.api_key}"},
                        ) as response:
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
    ) -> None:
        self.kie = kie
        self.neironych = neironych or NeironychWan3RuntimeService()
        self.primary_provider = primary_provider or self._configured_provider

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
                # Never catch an uncertain POST and start a second paid KIE job.
                result = await self.neironych.submit(
                    payload, idempotency_key=recipe.provider_submission_id,
                )
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
        if state == "done":
            # Marker is never passed to the public downloader.
            result["resultUrls"] = [provider_task_id]
        elif state in {"failed", "expired"}:
            result["failCode"] = state
            result["failMsg"] = str(record.get("error") or state)[:300]
        return result

    async def download_result(self, provider_task_id: str, *, task_id: str) -> str:
        if not provider_task_id.startswith(NEIRONYCH_TASK_PREFIX):
            raise ValueError("Not a native Neironych task")
        request_id = provider_task_id[len(NEIRONYCH_TASK_PREFIX):]
        return await self.neironych.download_managed(request_id, task_id=task_id)

    async def close(self) -> None:
        await self.kie.close()
