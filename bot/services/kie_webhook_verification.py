"""Treat KIE callbacks as wakeups; only authenticated provider records are trusted."""

from __future__ import annotations

import asyncio
import json
import logging
from functools import wraps
from typing import Any
from weakref import WeakValueDictionary

from bot import database
from bot.services.delivery_state import has_retryable_result, stored_result_payload
from bot.services.kie_market_service import kie_market_service
from bot.services.veo_service import veo_service

logger = logging.getLogger(__name__)
_SUCCESS = {"success", "completed", "succeeded", "finished"}
_FAILURE = {"fail", "failed", "error"}
_PENDING = {"waiting", "pending", "queuing", "queued", "generating", "processing"}


_CALLBACK_LOCKS: WeakValueDictionary[
    tuple[asyncio.AbstractEventLoop, str], asyncio.Lock
] = WeakValueDictionary()


def _callback_task_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    hint = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    task_id = hint.get("taskId") or hint.get("task_id") or hint.get("id")
    if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 256:
        return None
    return task_id.strip()


def serialize_kie_callback(handler):
    """Serialize a task's GET, retry creation, refund, and delivery in this worker.

    Production runs one bot process. Weak values release idle locks; waiters
    retain the same lock until the entire callback finishes. Multiple workers
    would require a database-backed processing claim before paid retry creation.
    """

    @wraps(handler)
    async def serialized(request):
        try:
            task_id = _callback_task_id(await request.json())
        except (ValueError, TypeError, UnicodeDecodeError):
            task_id = None
        if not task_id:
            return await handler(request)
        lock_key = (asyncio.get_running_loop(), task_id)
        lock = _CALLBACK_LOCKS.get(lock_key)
        if lock is None:
            lock = asyncio.Lock()
            _CALLBACK_LOCKS[lock_key] = lock
        async with lock:
            return await handler(request)

    return serialized


async def canonical_kie_callback(
    payload: Any,
) -> tuple[dict[str, Any] | None, int]:
    """Return a terminal canonical payload, an ignored wakeup, or retryable 503.

    Callback signatures do not authenticate status/result fields. Select the
    endpoint from our task, then fetch its current state with our API key.
    Unknown, terminal, and superseded task IDs must not trigger provider work.
    """
    task_id = _callback_task_id(payload)
    if not task_id:
        return None, 400
    try:
        task = await database.get_task_by_id(task_id)
    except Exception:
        logger.exception("KIE callback local lookup failed: task_id=%s", task_id)
        return None, 503
    if task and task.task_id == task_id and has_retryable_result(task):
        return stored_result_payload(task), 200
    if (
        not task
        or task.task_id != task_id
        or task.status not in {"pending", "processing"}
    ):
        return None, 200

    try:
        request_data = json.loads(task.request_data or "{}")
    except (TypeError, ValueError):
        request_data = {}
    if isinstance(request_data, dict):
        provider = str(request_data.get("provider") or "").lower()
        if provider in {"nexus", "rendergrid", "replicate", "novita"}:
            return None, 200

    try:
        if str(task.model or "").lower().startswith("veo"):
            result = await veo_service.get_video_details(task_id)
            if not isinstance(result, dict) or result.get("code") != 200:
                return None, 503
            canonical = result.get("data")
            if not isinstance(canonical, dict):
                return None, 503
            canonical = dict(canonical)
            flag = canonical.get("successFlag")
            state = {0: "generating", 1: "success", 2: "fail", 3: "fail"}.get(flag)
            if state is None:
                return None, 503
            canonical["state"] = state
            canonical["model"] = task.model
            canonical["info"] = canonical.get("response") or {}
            canonical["failCode"] = canonical.get("errorCode")
            canonical["failMsg"] = canonical.get("errorMessage")
        else:
            canonical = await kie_market_service.get_task_status(task_id)
    except Exception as exc:  # noqa: BLE001 - fail closed at the provider boundary.
        logger.warning(
            "KIE callback canonical lookup failed: task_id=%s reason=%s",
            task_id,
            type(exc).__name__,
        )
        return None, 503

    if not isinstance(canonical, dict) or canonical.get("taskId") != task_id:
        logger.warning(
            "KIE callback canonical record missing or mismatched: task_id=%s", task_id
        )
        return None, 503
    state = str(canonical.get("state") or canonical.get("status") or "").lower()
    if state in _PENDING:
        return None, 200
    if state not in _SUCCESS | _FAILURE:
        return None, 503

    # A provider retry may replace the external ID while the GET is in flight.
    try:
        current = await database.get_task_by_id(task_id)
    except Exception:
        logger.exception("KIE callback local recheck failed: task_id=%s", task_id)
        return None, 503
    if current and current.task_id == task_id and has_retryable_result(current):
        return stored_result_payload(current), 200
    if (
        not current
        or current.task_id != task_id
        or current.status not in {"pending", "processing"}
    ):
        return None, 200
    return {"code": 200, "data": dict(canonical)}, 200
