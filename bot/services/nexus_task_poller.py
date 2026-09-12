"""Persistent polling for pending asynchronous image-provider tasks."""

from __future__ import annotations

import json
import logging
from typing import Any

from bot import db as db_backend
from bot.database import DATABASE_PATH

logger = logging.getLogger(__name__)

NEXUS_POLL_INTERVAL_SECONDS = 3
NEXUS_POLL_BATCH_SIZE = 36
NEXUS_POLL_CONCURRENCY = 8
MANAGED_IMAGE_PROVIDERS = frozenset({"nexus", "rendergrid"})


async def get_pending_provider_image_tasks(
    *,
    limit: int = NEXUS_POLL_BATCH_SIZE,
) -> list[dict[str, Any]]:
    """Return pending images launched through providers that require polling."""

    safe_limit = max(1, min(int(limit or NEXUS_POLL_BATCH_SIZE), 50))
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT id, user_id, telegram_id, task_id, type, model, prompt, cost,
                   aspect_ratio, request_data, status, created_at, updated_at
            FROM generation_tasks
            WHERE status IN ('pending', 'processing')
              AND type = 'image'
            ORDER BY COALESCE(updated_at, created_at) ASC
            LIMIT ?
            """,
            (safe_limit * 5,),
        )
        rows = await cursor.fetchall()
        tasks: list[dict[str, Any]] = []
        for row in rows:
            task = dict(row)
            raw_request_data = task.get("request_data")
            if isinstance(raw_request_data, str) and raw_request_data.strip():
                try:
                    task["request_data"] = json.loads(raw_request_data)
                except json.JSONDecodeError:
                    logger.warning(
                        "Nexus poller: invalid request_data JSON for task %s",
                        task.get("task_id"),
                    )
                    task["request_data"] = {}
            elif not isinstance(raw_request_data, dict):
                task["request_data"] = {}
            provider = str(task["request_data"].get("provider") or "").strip().lower()
            if provider not in MANAGED_IMAGE_PROVIDERS:
                continue
            tasks.append(task)
            if len(tasks) >= safe_limit:
                break
        return tasks


async def get_pending_nexus_image_tasks(
    *,
    limit: int = NEXUS_POLL_BATCH_SIZE,
) -> list[dict[str, Any]]:
    """Backward-compatible alias for callers that still use the legacy name."""
    return await get_pending_provider_image_tasks(limit=limit)
