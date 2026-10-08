from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from bot import db as db_backend
from bot.database import DATABASE_PATH, generation_has_private_recipe

logger = logging.getLogger(__name__)

_PRIVATE_TASK_FIELDS = {
    "source_url",
    "pinterest_url",
    "publication_reference_images",
    "publication_reference_videos",
    "publication_reference_image_indices",
    "publication_reference_video_indices",
    "feed_reference_selection",
    "feed_repeat_reference_selection",
}
_PRIVATE_REQUEST_FIELDS = {
    "prompt",
    "effective_prompt",
    "source_url",
    "pinterest_url",
    "v_image_url",
    "first_frame_url",
    "last_frame_url",
    "reference_images",
    "source_reference_images",
    "private_repeat_reference_images",
    "omni_audio_ids",
    "omni_character_ids",
    "omni_character_audio_ids",
    "reference_image_urls",
    "provider_reference_images",
    "v_reference_videos",
    "reference_video_urls",
    "video_references",
    "provider_reference_videos",
    "v_reference_audio",
    "reference_audios",
    "reference_audio_urls",
    "audio_references",
    "reference_roles",
    "provider_reference_roles",
    "fixed_asset_ids",
    "reference_contract",
    "prompt_source_id",
    "seedance_reference_snapshot",
}


async def _protected_task_ids(task_ids: list[str]) -> set[str]:
    normalized = [
        str(task_id or "").strip()
        for task_id in task_ids
        if str(task_id or "").strip()
    ]
    if not normalized:
        return set()

    placeholders = ",".join("?" for _ in normalized)
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            f"""
            SELECT task_id, source_feed_gen_id, action_type, prompt, request_data
            FROM generation_tasks
            WHERE task_id IN ({placeholders})
            """,
            tuple(normalized),
        )
        rows = await cursor.fetchall()

    protected: set[str] = set()
    legacy_candidates: dict[str, str] = {}
    for row in rows:
        task_id = str(row["task_id"] or "").strip()
        prompt = str(row["prompt"] or "").strip()
        if generation_has_private_recipe(row):
            protected.add(task_id)
        elif prompt:
            legacy_candidates[task_id] = prompt

    if legacy_candidates:
        # Privacy only needs recipes, not public cards, settings or success metrics.
        # Do not paginate: historical matches must remain protected beyond page one.
        async with db_backend.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """SELECT prompt_text FROM user_prompts
                   WHERE status = 'approved' AND is_public = 1 AND tags LIKE ?""",
                ('%"trend"%',),
            )
            recipes = await cursor.fetchall()
        trend_prompts = {str(row[0] or "").strip() for row in recipes}
        protected.update(
            task_id for task_id, prompt in legacy_candidates.items()
            if prompt in trend_prompts
        )
    return protected


def _task_objects(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    task = payload.get("task")
    if isinstance(task, dict):
        tasks.append(task)
    recent = payload.get("recent_tasks")
    if isinstance(recent, list):
        tasks.extend(item for item in recent if isinstance(item, dict))
    return tasks


def _redact_private_request_data(value: Any) -> Any:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = {}
    if not isinstance(value, Mapping):
        return None
    clean = dict(value)
    for key in _PRIVATE_REQUEST_FIELDS:
        clean.pop(key, None)
    clean["prompt_hidden"] = True
    clean["prompt_actions_allowed"] = False
    return clean


async def sanitize_task_api_payload(payload: Any) -> Any:
    """Remove curated trend recipes and private source links from task APIs.

    This also covers tasks created before the dedicated trend runner existed by
    matching their stored prompt against approved curated trend prompts. Privacy
    fails closed: protected trend prompts, source/reference URLs and prompt
    actions never reach a Mini App task/history payload.
    """

    if not isinstance(payload, Mapping):
        return payload

    result = dict(payload)
    tasks = _task_objects(result)
    if not tasks:
        return result

    task_ids = [str(task.get("task_id") or "").strip() for task in tasks]
    try:
        protected = await _protected_task_ids(task_ids)
    except Exception:
        logger.exception("Unable to resolve protected trend task prompts")
        protected = {task_id for task_id in task_ids if task_id}

    def redact(task: dict[str, Any]) -> dict[str, Any]:
        task_id = str(task.get("task_id") or "").strip()
        if task_id not in protected and not generation_has_private_recipe(task):
            return task
        clean = dict(task)
        clean["prompt"] = ""
        clean["prompt_preview"] = ""
        clean["prompt_hidden"] = True
        clean["prompt_actions_allowed"] = False
        clean["feed_prompt_visible"] = False
        clean["feed_references_visible"] = False
        clean["request_data"] = _redact_private_request_data(clean.get("request_data"))
        for key in _PRIVATE_TASK_FIELDS:
            clean.pop(key, None)
        return clean

    if isinstance(result.get("task"), dict):
        result["task"] = redact(result["task"])
    if isinstance(result.get("recent_tasks"), list):
        result["recent_tasks"] = [
            redact(item) if isinstance(item, dict) else item
            for item in result["recent_tasks"]
        ]
    return result
