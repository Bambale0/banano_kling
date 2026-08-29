"""Exact, idempotent success metrics for curated trends.

``uses_count`` is an accepted-launch counter and therefore cannot truthfully be
presented as completed generations.  This compatibility layer records the
trend/task relation once and derives the public success count by joining that
relation with ``generation_tasks.status = 'completed'``.  Callback retries do
not increment anything, because one task can only contribute one joined row.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from bot import database
from bot import db as db_backend
from bot.database import DATABASE_PATH

logger = logging.getLogger(__name__)

_SCHEMA_LOCK: asyncio.Lock | None = None
_SCHEMA_READY = False
_INSTALLED = False
TREND_TAG = "trend"


def _schema_lock() -> asyncio.Lock:
    global _SCHEMA_LOCK
    if _SCHEMA_LOCK is None:
        _SCHEMA_LOCK = asyncio.Lock()
    return _SCHEMA_LOCK


async def ensure_trend_generation_run_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    async with _schema_lock():
        if _SCHEMA_READY:
            return
        async with db_backend.connect(DATABASE_PATH) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS trend_generation_runs (
                    task_id TEXT PRIMARY KEY,
                    trend_id BIGINT NOT NULL,
                    user_id BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_trend_generation_runs_trend
                ON trend_generation_runs(trend_id, created_at)
                """
            )
            await db.commit()
        _SCHEMA_READY = True


async def register_trend_generation_run(
    *,
    task_id: Any,
    trend_id: Any,
    user_id: Any = None,
) -> bool:
    task_key = str(task_id or "").strip()
    try:
        trend_key = int(trend_id)
    except (TypeError, ValueError):
        return False
    if not task_key or trend_key <= 0:
        return False

    normalized_user_id: int | None
    try:
        normalized_user_id = int(user_id) if user_id is not None else None
    except (TypeError, ValueError):
        normalized_user_id = None

    await ensure_trend_generation_run_schema()
    async with db_backend.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO trend_generation_runs(task_id, trend_id, user_id)
            VALUES (?, ?, ?)
            ON CONFLICT (task_id) DO NOTHING
            """,
            (task_key, trend_key, normalized_user_id),
        )
        await db.commit()
        return bool(cursor.rowcount)


async def get_trend_success_counts(trend_ids: list[int] | tuple[int, ...]) -> dict[int, int]:
    normalized = sorted({int(value) for value in trend_ids if int(value) > 0})
    if not normalized:
        return {}
    await ensure_trend_generation_run_schema()
    placeholders = ",".join("?" for _ in normalized)
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            f"""
            SELECT r.trend_id, COUNT(*) AS successful_runs_count
            FROM trend_generation_runs r
            JOIN generation_tasks g ON g.task_id = r.task_id
            WHERE r.trend_id IN ({placeholders})
              AND g.status = 'completed'
            GROUP BY r.trend_id
            """,
            tuple(normalized),
        )
        rows = await cursor.fetchall()
    return {
        int(row["trend_id"]): int(row["successful_runs_count"] or 0)
        for row in rows
    }


def _is_trend(prompt: Any) -> bool:
    if not isinstance(prompt, dict):
        return False
    tags = {
        str(tag or "").strip().lower()
        for tag in prompt.get("tags", []) or []
        if str(tag or "").strip()
    }
    return TREND_TAG in tags


def _public_counter_description(prompt: dict[str, Any], count: int) -> dict[str, Any]:
    enriched = dict(prompt)
    enriched["successful_runs_count"] = max(0, int(count))
    original = str(prompt.get("description") or "").strip()
    counter = f"✅ Успешных запусков: {max(0, int(count))}"
    enriched["description"] = f"{counter} · {original}" if original else counter
    return enriched


async def _enrich_prompt(prompt: Any, *, include_counter_in_description: bool) -> Any:
    if not _is_trend(prompt):
        return prompt
    trend_id = int(prompt.get("id") or 0)
    counts = await get_trend_success_counts([trend_id])
    count = counts.get(trend_id, 0)
    if include_counter_in_description:
        return _public_counter_description(prompt, count)
    enriched = dict(prompt)
    enriched["successful_runs_count"] = count
    return enriched


def _install_database_enrichment() -> None:
    if getattr(database, "_trend_success_metrics_installed", False):
        return

    original_get_prompts_by_tag = database.get_prompts_by_tag
    original_get_prompt_by_id = database.get_prompt_by_id

    @wraps(original_get_prompts_by_tag)
    async def get_prompts_by_tag(*args: Any, **kwargs: Any):
        prompts = await original_get_prompts_by_tag(*args, **kwargs)
        raw_tag = args[0] if args else kwargs.get("tag")
        if str(raw_tag or "").strip().lower() != TREND_TAG or not prompts:
            return prompts
        trend_ids = [int(item.get("id") or 0) for item in prompts if _is_trend(item)]
        counts = await get_trend_success_counts(trend_ids)
        return [
            _public_counter_description(item, counts.get(int(item.get("id") or 0), 0))
            if _is_trend(item)
            else item
            for item in prompts
        ]

    @wraps(original_get_prompt_by_id)
    async def get_prompt_by_id(*args: Any, **kwargs: Any):
        prompt = await original_get_prompt_by_id(*args, **kwargs)
        return await _enrich_prompt(prompt, include_counter_in_description=False)

    database.get_prompts_by_tag = get_prompts_by_tag
    database.get_prompt_by_id = get_prompt_by_id
    database._trend_success_metrics_installed = True


def _response_payload(response: Any) -> dict[str, Any] | None:
    body = getattr(response, "body", None)
    if not body:
        return None
    try:
        payload = json.loads(bytes(body))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


async def _record_response_task(response: Any, trend: Any, user: Any) -> None:
    payload = _response_payload(response)
    if not payload or payload.get("ok") is not True:
        return
    task_id = str(payload.get("task_id") or "").strip()
    trend_id = getattr(trend, "trend_id", None)
    user_id = getattr(user, "id", None)
    if not task_id or not trend_id:
        return
    try:
        inserted = await register_trend_generation_run(
            task_id=task_id,
            trend_id=trend_id,
            user_id=user_id,
        )
        logger.info(
            "Trend generation linked: trend_id=%s task_id=%s inserted=%s",
            trend_id,
            task_id,
            inserted,
        )
    except Exception:
        # Generation itself already launched successfully. Metrics must never
        # turn that user-facing success into a 500 response.
        logger.exception(
            "Failed to link trend generation: trend_id=%s task_id=%s",
            trend_id,
            task_id,
        )


def _install_trend_api_hooks() -> None:
    import bot.trend_api as trend_api

    if getattr(trend_api, "_trend_success_metrics_installed", False):
        return

    original_image = trend_api._run_image_trend
    original_video = trend_api._run_video_trend

    @wraps(original_image)
    async def run_image_trend(*args: Any, **kwargs: Any):
        response = await original_image(*args, **kwargs)
        await _record_response_task(response, kwargs.get("trend"), kwargs.get("user"))
        return response

    @wraps(original_video)
    async def run_video_trend(*args: Any, **kwargs: Any):
        response = await original_video(*args, **kwargs)
        await _record_response_task(response, kwargs.get("trend"), kwargs.get("user"))
        return response

    trend_api._run_image_trend = run_image_trend
    trend_api._run_video_trend = run_video_trend
    trend_api._trend_success_metrics_installed = True


def install_trend_success_compat() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _install_database_enrichment()
    _install_trend_api_hooks()
    _INSTALLED = True
