from __future__ import annotations

import json
import logging

from aiohttp import web

from bot import db as db_backend
from bot.config import config
from bot.database import get_master_partner_user, get_or_create_user
from bot.pinterest_trend_api import (
    _PINTEREST_TOOL_PROMPT,
    _PINTEREST_TOOL_SETTINGS,
    _PINTEREST_TOOL_TAG,
    _PINTEREST_TOOL_TAGS,
    _PINTEREST_TOOL_TITLE,
)

logger = logging.getLogger(__name__)


def _settings_with_preserved_preview_type(raw_settings) -> dict:
    settings = dict(_PINTEREST_TOOL_SETTINGS)
    try:
        existing = (
            json.loads(raw_settings)
            if isinstance(raw_settings, str) and raw_settings.strip()
            else dict(raw_settings or {})
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        existing = {}
    preview_type = str(existing.get("preview_type") or "").strip().lower()
    if preview_type in {"image", "video"}:
        settings["preview_type"] = preview_type
    return settings


async def _system_trend_author():
    """Return a valid DB author even when production has no ADMIN_IDS configured."""

    if config.admin_ids:
        return await get_or_create_user(config.admin_ids[0])
    logger.warning(
        "ADMIN_IDS is empty; Pinterest system trend uses the master system user"
    )
    return await get_master_partner_user()


async def ensure_pinterest_trend_catalog(_: web.Application) -> None:
    """Strictly guarantee that the Pinterest product tool exists in Trends.

    The older seed in ``pinterest_trend_api`` is intentionally best-effort for
    backwards compatibility. This verifier is product-critical and therefore
    does not swallow database errors: a deployment must not become healthy while
    the advertised system trend is missing from the catalog.
    """

    author = await _system_trend_author()
    tags_json = json.dumps(_PINTEREST_TOOL_TAGS, ensure_ascii=False)

    async with db_backend.connect() as db:
        # Both SQLite and the PostgreSQL compatibility layer support the shared
        # Row mapping. Without this, SQLite returns tuples and the strict
        # verifier crashes when reading generation_settings by column name.
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT id, generation_settings
            FROM user_prompts
            WHERE title = ? OR tags LIKE ?
            ORDER BY id ASC
            LIMIT 1
            """,
            (_PINTEREST_TOOL_TITLE, f'%"{_PINTEREST_TOOL_TAG}"%'),
        )
        row = await cursor.fetchone()
        settings_json = json.dumps(
            _settings_with_preserved_preview_type(
                row["generation_settings"] if row else None
            ),
            ensure_ascii=False,
        )

        if row:
            await db.execute(
                """
                UPDATE user_prompts
                SET title = ?,
                    description = ?,
                    category = 'photo',
                    prompt_text = ?,
                    model = 'banana_pro',
                    tags = ?,
                    generation_settings = ?,
                    is_public = TRUE,
                    status = 'approved',
                    reject_reason = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    _PINTEREST_TOOL_TITLE,
                    "Повтори сцену, свет и позу с Pinterest — со своей внешностью",
                    _PINTEREST_TOOL_PROMPT,
                    tags_json,
                    settings_json,
                    int(row["id"]),
                ),
            )
            trend_id = int(row["id"])
        else:
            await db.execute(
                """
                INSERT INTO user_prompts (
                    author_id,
                    title,
                    description,
                    category,
                    prompt_text,
                    preview_url,
                    model,
                    tags,
                    generation_settings,
                    likes,
                    uses_count,
                    is_public,
                    status,
                    created_at
                ) VALUES (?, ?, ?, 'photo', ?, NULL, 'banana_pro', ?, ?, 0, 0, TRUE, 'approved', CURRENT_TIMESTAMP)
                """,
                (
                    int(author.id),
                    _PINTEREST_TOOL_TITLE,
                    "Повтори сцену, свет и позу с Pinterest — со своей внешностью",
                    _PINTEREST_TOOL_PROMPT,
                    tags_json,
                    settings_json,
                ),
            )
            cursor = await db.execute(
                """
                SELECT id
                FROM user_prompts
                WHERE title = ? OR tags LIKE ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (_PINTEREST_TOOL_TITLE, f'%"{_PINTEREST_TOOL_TAG}"%'),
            )
            inserted = await cursor.fetchone()
            if not inserted:
                raise RuntimeError("Pinterest trend insert completed without a catalog row")
            trend_id = int(inserted["id"])

        await db.commit()

    logger.info(
        "Required Pinterest trend catalog entry is ready: id=%s model=banana_pro quality=2K ratio=9:16",
        trend_id,
    )
