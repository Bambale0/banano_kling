"""Durable configurable Seedance routing, shared by Telegram and Mini App."""

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
UNRESOLVED_PHASES = {
    "ready",
    "submitting",
    "submitted",
    "kie_ready",
    "kie_submitting",
    "kie_uncertain",
    "kie_submitted",
}
SCHEMA = """CREATE TABLE IF NOT EXISTS seedance_provider_routes (
    task_id TEXT PRIMARY KEY, payload TEXT NOT NULL, phase TEXT NOT NULL,
    request_id TEXT, result_url TEXT, failure_code TEXT, fallback_payload TEXT,
    lease_until DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    download_attempts INTEGER NOT NULL DEFAULT 0
)"""


def enabled() -> bool:
    return (
        os.getenv("SEEDANCE_FALLBACK_PROVIDER", "neironych").strip().lower()
        == "neironych"
        and neironych_seedance_admin_service.enabled
    )


def neironych_primary() -> bool:
    return os.getenv("SEEDANCE_PRIMARY_PROVIDER", "kie").strip().lower() == "neironych"


def _kie_fallback_enabled() -> bool:
    return os.getenv("SEEDANCE_FALLBACK_PROVIDER", "kie").strip().lower() == "kie"


def _uses_kie_fallback(payload: dict) -> bool:
    return (
        payload.get("_seedance_primary_provider") == "neironych"
        and payload.get("_seedance_fallback_provider") == "kie"
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
    await cleanup_seedance_routes()


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


def _positive_setting(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


async def _fail_route(task_id: str, model: str, code: str) -> None:
    await _update(
        task_id,
        phase="failed",
        failure_code=code,
        lease_until=0,
        payload=json.dumps({"model": model}),
        fallback_payload=None,
    )


async def cleanup_seedance_routes() -> int:
    async with db_backend.connect() as db:
        if not await _table_exists(db) or not await _table_exists(
            db, "generation_tasks"
        ):
            return 0
        cutoff = (
            "CURRENT_TIMESTAMP - (? * INTERVAL '1 second')"
            if db_backend.is_postgres()
            else "datetime('now', '-' || ? || ' seconds')"
        )
        cursor = await db.execute(
            "DELETE FROM seedance_provider_routes WHERE phase IN ('ready', 'primary') "
            "AND request_id IS NULL AND created_at < "
            + cutoff
            + " AND NOT EXISTS (SELECT 1 FROM generation_tasks g "
            "WHERE g.task_id = seedance_provider_routes.task_id)",
            (_positive_setting("SEEDANCE_FALLBACK_ORPHAN_TTL_SECONDS", 86400),),
        )
        await db.commit()
        return max(0, cursor.rowcount)


async def _claim_content(task_id: str) -> bool:
    now = time.time()
    lease = (
        max(300, neironych_seedance_admin_service.timeout_seconds)
        * NeironychSeedanceAdminService.CONTENT_DOWNLOAD_ATTEMPTS
        + 30
    )
    async with db_backend.connect() as db:
        cursor = await db.execute(
            "UPDATE seedance_provider_routes SET lease_until = ? "
            "WHERE task_id = ? AND phase = 'submitted' AND lease_until < ? RETURNING task_id",
            (now + lease, task_id, now),
        )
        claimed = await cursor.fetchone()
        await db.commit()
        return bool(claimed)


async def _content_failed(route: dict, error: Exception) -> dict:
    async with db_backend.connect() as db:
        row = await (
            await db.execute(
                "UPDATE seedance_provider_routes SET download_attempts = download_attempts + 1, lease_until = 0 "
                "WHERE task_id = ? AND phase = 'submitted' RETURNING download_attempts",
                (route["task_id"],),
            )
        ).fetchone()
        await db.commit()
    attempts = int(row[0]) if row else 0
    logger.warning(
        "Seedance fallback content unavailable: task_id=%s request_id=%s attempt=%s error_type=%s status=%s",
        route["task_id"],
        route["request_id"],
        attempts,
        type(error).__name__,
        getattr(error, "status", None),
    )
    if attempts >= _positive_setting("SEEDANCE_FALLBACK_CONTENT_ATTEMPTS", 3):
        await _fail_route(
            route["task_id"],
            json.loads(route["payload"])["model"],
            "content_unavailable",
        )
        return _record(route, "fail", code="content_unavailable")
    return _record(route, "generating")


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
        or payload.get("_seedance_edit_intent") is True
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
    payload: dict,
    primary: Callable[[dict], Awaitable[dict]],
    *,
    video_editing: bool = False,
) -> dict:
    wire_payload = payload
    if video_editing:
        # Application intent is persisted locally, never added to KIE wire data.
        payload = {**payload, "_seedance_edit_intent": True}
    if payload.get("model") in MODELS and neironych_primary():
        try:
            _payload(payload)
            compatible = neironych_seedance_admin_service.enabled
        except ValueError:
            compatible = False
        if compatible:
            task_id = "seedance_nr_" + uuid.uuid4().hex
            await _register(
                task_id,
                {
                    **payload,
                    "_seedance_primary_provider": "neironych",
                    "_seedance_fallback_provider": "kie"
                    if _kie_fallback_enabled()
                    else "none",
                },
                "ready",
            )
            logger.info(
                "Seedance route selected: task_id=%s primary=neironych", task_id
            )
            return {"task_id": task_id, "status": "pending", "provider": "neironych"}
        # Preserve unsupported controls exactly; do not silently drop them.
        if not _kie_fallback_enabled():
            return {"error": "unsupported_primary_parameters", "status": "failed"}
        logger.info(
            "Seedance compatibility route selected: model=%s provider=kie",
            payload["model"],
        )
        return await primary(wire_payload)
    result = await primary(wire_payload)
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
            if not await _table_exists(db, "generation_tasks"):
                await db.rollback()
                return
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
        await _fail_route(task_id, payload["model"], "unsupported_fallback_parameters")
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
        if exc.status in {400, 401, 402, 403, 404, 422, 429}:
            await _neironych_failed(task_id, payload, str(exc.status))
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


async def _neironych_failed(task_id: str, payload: dict, code: str) -> None:
    if not _uses_kie_fallback(payload):
        await _fail_route(task_id, payload["model"], code)
        return
    async with db_backend.connect() as db:
        await db.execute(
            "UPDATE seedance_provider_routes SET phase='kie_ready', request_id=NULL, "
            "failure_code=?, lease_until=0, fallback_payload=NULL "
            "WHERE task_id=? AND phase IN ('submitting', 'submitted')",
            (code, task_id),
        )
        await db.commit()
    logger.warning(
        "Seedance provider switch: task_id=%s from=neironych to=kie reason=%s",
        task_id,
        code,
    )


async def _submit_kie_fallback(task_id: str) -> None:
    """KIE has no verified idempotent create: never repeat uncertain submission."""
    from bot.services.kling_service import KlingService

    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        active = await (
            await db.execute(
                "UPDATE generation_tasks SET updated_at=updated_at WHERE task_id=? "
                "AND status IN ('pending','processing') RETURNING task_id",
                (task_id,),
            )
        ).fetchone()
        if not active:
            await db.rollback()
            return
        row = await (
            await db.execute(
                "UPDATE seedance_provider_routes SET phase='kie_submitting', lease_until=? "
                "WHERE task_id=? AND phase='kie_ready' RETURNING payload",
                (time.time() + KlingService.CREATE_TASK_TIMEOUT_SECONDS + 30, task_id),
            )
        ).fetchone()
        await db.commit()
    if not row:
        return
    payload = json.loads(row["payload"])
    # Local receipt is stable. Remote-ID callbacks must not bypass this route.
    wire = {"model": payload["model"], "input": payload["input"]}
    try:
        result = await KlingService(kie_key=config.KIE_AI_API_KEY)._kie_post(
            KlingService.CREATE_TASK_ENDPOINT,
            wire,
        )
    except Exception as exc:  # noqa: BLE001 - acceptance is uncertain
        logger.error(
            "Seedance KIE fallback uncertain: task_id=%s error_type=%s",
            task_id,
            type(exc).__name__,
        )
        result = {"error": "network_error"}
    if result.get("task_id"):
        await _update(
            task_id, phase="kie_submitted", request_id=result["task_id"], lease_until=0
        )
        logger.info(
            "Seedance KIE fallback accepted: task_id=%s request_id=%s",
            task_id,
            result["task_id"],
        )
        return
    raw = result.get("raw") or {}
    inner = raw.get("data") if isinstance(raw, dict) else None
    accepted_id = (
        inner.get("taskId") or inner.get("task_id") if isinstance(inner, dict) else None
    )
    if accepted_id:
        await _update(
            task_id, phase="kie_submitted", request_id=accepted_id, lease_until=0
        )
    elif result.get("error") == "missing_api_key" or (
        result.get("error") == "api_error"
        and result.get("status_code") in {400, 401, 402, 403, 404, 422, 429, 455}
    ):
        await _fail_route(task_id, payload["model"], "kie_create_rejected")
    else:
        await _update(task_id, phase="kie_uncertain", lease_until=0)
        logger.error(
            "Seedance KIE fallback needs reconciliation: task_id=%s acceptance=unknown",
            task_id,
        )


async def _resolve_kie_fallback(route: dict) -> dict:
    from bot.services.kie_market_service import KIE_MARKET_API_BASE, KieMarketService

    task_id = route["task_id"]
    if route["phase"] == "kie_ready":
        await _submit_kie_fallback(task_id)
        route = await _load(task_id)
    if route["phase"] == "failed":
        return _record(route, "fail", code=route["failure_code"])
    if route.get("result_url"):
        return _record(route, "success", url=route["result_url"])
    if route["phase"] != "kie_submitted":
        return _record(route, "generating")
    market = KieMarketService()
    try:
        response = await market._get_json(
            f"{KIE_MARKET_API_BASE}/api/v1/jobs/recordInfo",
            params={"taskId": route["request_id"]},
        )
        data = response.get("data") if response.get("code") == 200 else None
        if not isinstance(data, dict) or data.get("taskId") != route["request_id"]:
            return _record(route, "generating")
        state = str(data.get("state") or "").lower()
        if state in FAILURES:
            await _fail_route(
                task_id, json.loads(route["payload"])["model"], "kie_generation_failed"
            )
            return _record(route, "fail", code="kie_generation_failed")
        if state not in {"success", "completed", "done", "succeeded", "finished"}:
            return _record(route, "generating")
        urls = market.parse_result_urls(data)
        if not urls:
            return _record(route, "generating")
        await _update(
            task_id,
            phase="kie_completed",
            result_url=urls[0],
            lease_until=0,
            payload=json.dumps({"model": json.loads(route["payload"])["model"]}),
        )
        return _record(route, "success", url=urls[0])
    except Exception as exc:  # noqa: BLE001 - outage must not become a refund
        logger.warning(
            "Seedance KIE fallback poll unresolved: task_id=%s error_type=%s",
            task_id,
            type(exc).__name__,
        )
        return _record(route, "generating")
    finally:
        await market.close()


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
    if route["phase"].startswith("kie_"):
        return await _resolve_kie_fallback(route)
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
        if not neironych_seedance_admin_service.enabled:
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
    if route["phase"].startswith("kie_"):
        return await _resolve_kie_fallback(route)
    if route["phase"] == "failed":
        return _record(route, "fail", code=route["failure_code"] or "provider_failed")
    if route.get("result_url"):
        return _record(route, "success", url=route["result_url"])
    if not route.get("request_id"):
        return _record(route, "generating")
    downloading = False
    try:
        record = await neironych_seedance_admin_service.get_status(route["request_id"])
        state = str(record.get("status") or "").lower()
        if state in {"failed", "expired"}:
            await _neironych_failed(
                task_id, json.loads(route["payload"]), "neironych_" + state
            )
            current = await _load(task_id)
            if current["phase"].startswith("kie_"):
                return await _resolve_kie_fallback(current)
            return _record(route, "fail", code="neironych_" + state)
        if state != "done":
            return _record(route, "generating")
        if not await _claim_content(task_id):
            return _record(route, "generating")
        downloading = True
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
            lease_until=0,
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
        RuntimeError,
    ) as exc:
        if downloading:
            return await _content_failed(route, exc)
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
        route and route["phase"] in UNRESOLVED_PHASES and not route.get("result_url")
    )


async def _table_exists(db: Any, table_name: str = "seedance_provider_routes") -> bool:
    if db_backend.is_postgres():
        cursor = await db.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema() "
            "AND tablename = ?",
            (table_name,),
        )
    else:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
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
    return bool(row and row["phase"] in UNRESOLVED_PHASES and not row["result_url"])
