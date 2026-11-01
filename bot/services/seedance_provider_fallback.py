"""Durable Seedance KIE -> Neironych fallback, shared by all product surfaces."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import aiohttp

from bot import db as db_backend
from bot.config import config
from bot.services.neironych_seedance_admin_service import (
    NeironychAPIError,
    NeironychSeedanceAdminService,
    neironych_seedance_admin_service,
)

logger = logging.getLogger(__name__)
MODELS = {
    "bytedance/seedance-2": "seedance-2.0",
    "bytedance/seedance-2-5": "seedance-2.5",
}
FAILURES = {"fail", "failed", "error"}
SCHEMA = """CREATE TABLE IF NOT EXISTS seedance_provider_routes (
    task_id TEXT PRIMARY KEY, payload TEXT NOT NULL, phase TEXT NOT NULL,
    request_id TEXT, result_url TEXT, failure_code TEXT, fallback_payload TEXT,
    lease_until DOUBLE PRECISION NOT NULL DEFAULT 0
)"""


def enabled() -> bool:
    return (
        os.getenv("SEEDANCE_FALLBACK_PROVIDER", "neironych").strip().lower()
        == "neironych"
        and neironych_seedance_admin_service.enabled
    )


async def _load(task_id: str) -> dict[str, Any] | None:
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        if not await _table_exists(db):
            return None
        row = await (
            await db.execute(
                "SELECT * FROM seedance_provider_routes WHERE task_id = ?", (task_id,)
            )
        ).fetchone()
        await db.commit()
        return dict(row) if row else None


async def _register(task_id: str, payload: dict, phase: str) -> None:
    async with db_backend.connect() as db:
        if db_backend.is_postgres():
            await db.execute("SELECT pg_advisory_xact_lock(178491, 20261101)")
        native_ddl = getattr(db, "execute_native_ddl", None)
        if native_ddl is not None:
            await native_ddl(SCHEMA)
        else:
            await db.execute(SCHEMA)
        await db.execute(
            "INSERT INTO seedance_provider_routes (task_id, payload, phase) VALUES (?, ?, ?) "
            "ON CONFLICT (task_id) DO NOTHING",
            (task_id, json.dumps(payload), phase),
        )
        await db.commit()


async def _update(task_id: str, **fields: Any) -> None:
    # All field names are internal constants; values are bound parameters.
    async with db_backend.connect() as db:
        await db.execute(
            "UPDATE seedance_provider_routes SET "
            + ", ".join(f"{key} = ?" for key in fields)
            + " WHERE task_id = ?",
            (*fields.values(), task_id),
        )
        await db.commit()


async def _retire_primary(task_id: str) -> None:
    async with db_backend.connect() as db:
        await db.execute(
            "DELETE FROM seedance_provider_routes WHERE task_id = ? AND phase = 'primary'",
            (task_id,),
        )
        await db.commit()


def _payload(payload: dict) -> dict:
    data = payload["input"]
    if (
        data.get("generate_audio") is False
        or data.get("return_last_frame") is True
        or data.get("output_format", "mp4") != "mp4"
        or data.get("web_search") is True
        or data.get("nsfw_checker") is True
    ):
        raise ValueError("unsupported_fallback_controls")
    model = MODELS[payload["model"]]
    images = data.get("reference_image_urls") or []
    videos = data.get("reference_video_urls") or []
    audios = data.get("reference_audio_urls") or []
    first, last = data.get("first_frame_url") or "", data.get("last_frame_url") or ""
    edit = model == "seedance-2.5" and (
        data.get("omni_reference_task_type") == "edit"
        or (data.get("duration") == -1 and videos)
    )
    mode = (
        "edit"
        if edit
        else "frames"
        if first or last
        else "reference"
        if images or videos or audios
        else "text"
    )
    result = NeironychSeedanceAdminService.build_payload(
        model=model,
        mode=mode,
        prompt=data["prompt"],
        duration=data["duration"],
        resolution=data["resolution"],
        aspect_ratio=data["aspect_ratio"],
        reference_images=images,
        reference_videos=videos,
        reference_audios=audios,
        start_image=first,
        end_image=last,
    )
    # The canonical video API uses its own defaults. Live probes confirmed
    # that forwarding KIE-only default controls is rejected downstream.
    # Non-default unsupported controls are rejected above, never discarded.
    return result


def _rejected(result: dict) -> bool:
    try:
        codes = {
            int(v.strip())
            for v in os.getenv(
                "SEEDANCE_FALLBACK_CREATE_CODES", "402,429,455,500,501,503,505"
            ).split(",")
            if v.strip()
        }
        status = int(result.get("status_code") or 0)
    except (ValueError, TypeError):
        return False
    raw = result.get("raw") or {}
    inner = raw.get("data") if isinstance(raw, dict) else None
    if isinstance(inner, dict) and (inner.get("taskId") or inner.get("task_id")):
        return False
    return result.get("error") == "api_error" and status in codes


async def submit_seedance(
    payload: dict, primary: Callable[[dict], Awaitable[dict]]
) -> dict:
    result = await primary(payload)
    if payload.get("model") not in MODELS or not enabled():
        return result
    task_id = result.get("task_id")
    if task_id:
        try:
            await _register(task_id, payload, "primary")
        except Exception:
            # Primary accepted: retain its ID and let its ordinary webhook finish.
            logger.exception(
                "Seedance fallback route persistence failed: task_id=%s", task_id
            )
        return result
    if not _rejected(result):
        return result
    try:
        _payload(payload)  # Validate compatibility before promising a fallback.
    except ValueError:
        logger.warning(
            "Seedance fallback unsupported parameters: model=%s", payload["model"]
        )
        return result
    task_id = "seedance_nr_" + uuid.uuid4().hex
    await _register(task_id, payload, "ready")
    # Return the durable receipt before paid submission. Product callers attach
    # it to their user/generation row; polling only launches after that binding.
    return {"task_id": task_id, "status": "pending", "provider": "neironych"}


async def _submit_fallback(task_id: str) -> None:
    # A lease prevents concurrent launches. An expired/uncertain launch reuses
    # the same provider idempotency key and the persisted exact payload.
    now = time.time()
    lease = max(180, neironych_seedance_admin_service.timeout_seconds + 30)
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        current = await (
            await db.execute(
                "SELECT phase FROM seedance_provider_routes WHERE task_id = ?",
                (task_id,),
            )
        ).fetchone()
        if current:
            # Lock in the same order as the refund path. A task already failed,
            # refunded, completed or superseded must never launch paid fallback.
            active = await (
                await db.execute(
                    "UPDATE generation_tasks SET updated_at = updated_at "
                    "WHERE task_id = ? AND status IN ('pending', 'processing') RETURNING task_id",
                    (task_id,),
                )
            ).fetchone()
            if not active:
                await db.rollback()
                return
        cursor = await db.execute(
            "UPDATE seedance_provider_routes SET phase = 'submitting', lease_until = ? "
            "WHERE task_id = ? AND phase IN ('primary', 'ready', 'submitting') AND lease_until < ? "
            "RETURNING payload, fallback_payload",
            (now + lease, task_id, now),
        )
        row = await cursor.fetchone()
        await db.commit()
    if not row:
        return
    payload = json.loads(row["payload"])
    try:
        body = (
            json.loads(row["fallback_payload"])
            if row["fallback_payload"]
            else _payload(payload)
        )
        if not row["fallback_payload"]:
            await _update(task_id, fallback_payload=json.dumps(body))
    except ValueError:
        await _update(
            task_id,
            phase="failed",
            failure_code="unsupported_fallback_parameters",
            lease_until=0,
        )
        return
    logger.info(
        "Seedance fallback submit: task_id=%s model=%s provider=neironych",
        task_id,
        body["model"],
    )
    try:
        result = await neironych_seedance_admin_service.submit(
            body,
            idempotency_key="tanya-seedance-fallback-"
            + hashlib.sha256(task_id.encode()).hexdigest(),
        )
    except NeironychAPIError as exc:
        # 409, 5xx and transport failures can mean accepted. Reconcile with
        # precisely the same key, never create another provider attempt.
        if exc.status in {400, 401, 402, 403, 404, 422}:
            await _update(
                task_id, phase="failed", failure_code=str(exc.status), lease_until=0
            )
        logger.warning(
            "Seedance fallback submission response: task_id=%s status=%s",
            task_id,
            exc.status,
        )
        return
    except (OSError, TimeoutError, RuntimeError) as exc:
        logger.warning(
            "Seedance fallback submission uncertain: task_id=%s error_type=%s",
            task_id,
            type(exc).__name__,
        )
        return
    except Exception as exc:  # noqa: BLE001 - preserve idempotent receipt on unknown acceptance
        logger.warning(
            "Seedance fallback submission uncertain: task_id=%s error_type=%s",
            task_id,
            type(exc).__name__,
        )
        return
    await _update(
        task_id, phase="submitted", request_id=result["request_id"], lease_until=0
    )
    logger.info(
        "Seedance fallback accepted: task_id=%s request_id=%s",
        task_id,
        result["request_id"],
    )


def _record(
    route: dict, state: str, *, url: str | None = None, code: str | None = None
) -> dict:
    payload = json.loads(route["payload"])
    return {
        "taskId": route["task_id"],
        "model": payload["model"],
        "state": state,
        "resultJson": json.dumps({"resultUrls": [url] if url else []}),
        "failCode": code,
        "failMsg": "Generation failed" if code else "",
    }


async def resolve_seedance_status(
    task_id: str, get_primary: Callable[..., Awaitable[dict]]
) -> dict | None:
    route = await _load(task_id)
    if not route:
        return None
    if route["phase"] == "primary":
        canonical = await get_primary()
        data = canonical.get("data") if canonical.get("code") == 200 else None
        if not isinstance(data, dict) or data.get("taskId") != task_id:
            return None
        state = str(data.get("state") or data.get("status") or "").lower()
        if state in {"success", "completed", "done", "succeeded", "finished"}:
            await _retire_primary(task_id)
            return data
        if state not in FAILURES:
            return data
        if not enabled():
            await _retire_primary(task_id)
            return data
        # A terminal authenticated provider record proves no active primary
        # generation remains. The exact stored media/controls are reused.
        try:
            _payload(json.loads(route["payload"]))
        except ValueError:
            await _retire_primary(task_id)
            return data
        await _submit_fallback(task_id)
        route = await _load(task_id)
        if route["phase"] == "primary":
            await _retire_primary(task_id)
            return data
    if route["phase"] in {"ready", "submitting"}:
        await _submit_fallback(task_id)
        route = await _load(task_id)
    if route["phase"] == "failed":
        return _record(route, "fail", code=route["failure_code"] or "provider_failed")
    if route.get("result_url"):
        return _record(route, "success", url=route["result_url"])
    if not route.get("request_id"):
        return _record(route, "generating")
    try:
        record = await neironych_seedance_admin_service.get_status(route["request_id"])
        state = str(record.get("status") or "").lower()
        if state in {"failed", "expired"}:
            await _update(task_id, phase="failed", failure_code="neironych_" + state)
            return _record(route, "fail", code="neironych_" + state)
        if state != "done":
            return _record(route, "generating")
        source = await neironych_seedance_admin_service.download_to_temp(
            route["request_id"]
        )
        safe_id = hashlib.sha256(route["request_id"].encode()).hexdigest()
        filename = "seedance-fallback-" + safe_id + ".mp4"
        target = Path("static/uploads/seedance_fallback") / filename

        def persist() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + "." + uuid.uuid4().hex + ".part")
            try:
                shutil.copyfile(source, temp)
                if temp.stat().st_size == 0:
                    raise ValueError("Neironych returned empty video content")
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)
                Path(source).unlink(missing_ok=True)

        await asyncio.to_thread(persist)
        url = config.static_base_url + "/uploads/seedance_fallback/" + filename
        await _update(
            task_id,
            result_url=url,
            phase="completed",
            fallback_payload=None,
            payload=json.dumps({"model": json.loads(route["payload"])["model"]}),
        )
        logger.info(
            "Seedance fallback result stored: task_id=%s request_id=%s",
            task_id,
            route["request_id"],
        )
        return _record(route, "success", url=url)
    except (
        NeironychAPIError,
        aiohttp.ClientError,
        OSError,
        TimeoutError,
        ValueError,
    ) as exc:
        logger.warning(
            "Seedance fallback result unresolved: task_id=%s request_id=%s error_type=%s status=%s",
            task_id,
            route["request_id"],
            type(exc).__name__,
            getattr(exc, "status", None),
        )
        return _record(route, "generating")


async def has_unresolved_fallback(task_id: str) -> bool:
    route = await _load(task_id)
    return bool(
        route
        and route["phase"] in {"ready", "submitting", "submitted"}
        and not route.get("result_url")
    )


async def _table_exists(db: Any) -> bool:
    if db_backend.is_postgres():
        cursor = await db.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema() "
            "AND tablename = 'seedance_provider_routes'"
        )
    else:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'seedance_provider_routes'"
        )
    return bool(await cursor.fetchone())


async def unresolved_in_transaction(db: Any, task_id: str) -> bool:
    # Legacy tasks can predate the routing table. Never issue a failing query
    # inside a PostgreSQL transaction.
    if not await _table_exists(db):
        return False
    row = await (
        await db.execute(
            "SELECT phase, result_url FROM seedance_provider_routes WHERE task_id = ?",
            (task_id,),
        )
    ).fetchone()
    return bool(
        row
        and row["phase"] in {"ready", "submitting", "submitted"}
        and not row["result_url"]
    )
