"""Compatibility lookup for repeat buttons with local/provider task aliases.

Telegram result messages can carry either the local public id (``img_*``) or a
provider task id. During queued image generation the database row may move from
the local id to the provider id while the local id is preserved only in
``request_data.task_id_aliases``. Some production SQLite builds also make the
JSON1 alias query brittle. This module installs a conservative fallback lookup
that searches the serialized request snapshot when the primary lookup misses.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable

from bot import database as database_module
from bot import db as db_backend

logger = logging.getLogger(__name__)

TaskLookup = Callable[[str], Awaitable[Any]]
_IMG_ID_RE = re.compile(r"img_[0-9a-fA-F]{8,32}")
_HEX_SHORT_RE = re.compile(r"[0-9a-fA-F]{8,32}")
_ORIGINAL_LOOKUP: TaskLookup | None = None
_PATCHED_LOOKUP: TaskLookup | None = None


def _candidate_task_ids(raw: Any) -> list[str]:
    value = str(raw or "").strip()
    candidates: list[str] = []

    def add(item: str) -> None:
        item = str(item or "").strip()
        if item and item not in candidates:
            candidates.append(item)

    add(value)
    for match in _IMG_ID_RE.findall(value):
        add(match)
    if value.startswith("img_"):
        add(value[4:])
    for match in _HEX_SHORT_RE.findall(value):
        add(match)
        add(f"img_{match}")
    return candidates


async def _find_canonical_task_id_by_serialized_alias(
    candidates: list[str],
) -> str | None:
    if not candidates:
        return None

    async with db_backend.connect(database_module.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        for candidate in candidates:
            like_value = f"%{candidate}%"
            cursor = await db.execute(
                """
                SELECT id, task_id
                FROM generation_tasks
                WHERE task_id = ?
                   OR request_data LIKE ?
                ORDER BY
                    CASE WHEN task_id = ? THEN 0 ELSE 1 END,
                    id DESC
                LIMIT 1
                """,
                (candidate, like_value, candidate),
            )
            row = await cursor.fetchone()
            if row:
                canonical = str(row["task_id"] or "").strip()
                if canonical:
                    return canonical
                return str(row["id"])
    return None


def install_repeat_lookup_compat(*modules: Any) -> None:
    """Patch repeat handlers to resolve local ids, provider ids and aliases."""

    global _ORIGINAL_LOOKUP, _PATCHED_LOOKUP
    if _ORIGINAL_LOOKUP is None:
        _ORIGINAL_LOOKUP = database_module.get_task_by_id
    original_lookup = _ORIGINAL_LOOKUP

    if _PATCHED_LOOKUP is None:

        async def compatible_get_task_by_id(task_id: str):
            candidates = _candidate_task_ids(task_id)
            for candidate in candidates:
                task = await original_lookup(candidate)
                if task:
                    return task

            canonical = await _find_canonical_task_id_by_serialized_alias(candidates)
            if canonical:
                task = await original_lookup(canonical)
                if task:
                    logger.info(
                        "Repeat lookup recovered task: requested=%s canonical=%s",
                        task_id,
                        canonical,
                    )
                    return task
            return None

        _PATCHED_LOOKUP = compatible_get_task_by_id

    database_module.get_task_by_id = _PATCHED_LOOKUP
    for module in modules:
        if module is not None and hasattr(module, "get_task_by_id"):
            setattr(module, "get_task_by_id", _PATCHED_LOOKUP)
