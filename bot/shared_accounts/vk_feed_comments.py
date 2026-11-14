"""Native VK comments in the common public feed, without Telegram user IDs.

Writes use a separate actor-keyed table. Every write checks current public
visibility and atomically enforces idempotency + per-actor rate-limit bucket.
The same feed readers combine native and legacy comments.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from weakref import WeakValueDictionary
from typing import Any

from bot import database
from bot import db as db_backend

_KEY_RE = re.compile(r"[A-Za-z0-9_-]{16,80}\Z")
MAX_COMMENT_CHARS = 500

# SQLite supports only one concurrent writer; new aiosqlite connections
# reconfigure PRAGMA journal_mode=WAL before their busy_timeout. Concurrent
# opening can fail with SQLITE_BUSY even on the same idempotency claim.
# Share a short-lived, loop-local writer lock, not a process-global lock
# bound to a previous async event loop. Weak values avoid leaked test loops.
_SQLITE_WRITER_LOCKS: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()


def _sqlite_writer_lock() -> asyncio.Lock:
    loop_key = id(asyncio.get_running_loop())
    lock = _SQLITE_WRITER_LOCKS.get(loop_key)
    if lock is None:
        lock = asyncio.Lock()
        _SQLITE_WRITER_LOCKS[loop_key] = lock
    return lock




class VkCommentConflict(Exception):
    """Same native idempotency key was used with a different comment."""


class VkCommentCooldown(Exception):
    """Native actor already wrote a comment during the current rate bucket."""


def _rate_seconds() -> int:
    raw = os.getenv("VK_MINIAPP_FEED_COMMENT_COOLDOWN_SECONDS", "10")
    try:
        seconds = int(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Invalid VK comment cooldown configuration") from exc
    if not 1 <= seconds <= 3600:
        raise RuntimeError("VK comment cooldown configuration outside allowed bounds")
    return seconds


def _native_comment_payload(row: Any, *, viewer_vk_user_id: int | None = None) -> dict:
    return {
        "id": f"vk:{int(row['id'])}",
        "gen_id": int(row["generation_id"]),
        "text": str(row["text"]),
        # Do not accept a caller-chosen author display or leak public VK IDs.
        "author": "Участник ВКонтакте",
        "author_referral_code": None,
        "is_mine": type(viewer_vk_user_id) is int and row["vk_user_id"] == viewer_vk_user_id,
        "created_at": str(row["created_at"]),
    }


async def create_public_vk_comment(
    vk_actor_id: int, gen_id: int, comment_text: str, client_request_id: str,
) -> dict | None:
    """Expose an idempotent API while serializing SQLite-only writer opens.

    PostgreSQL remains fully concurrent; DB unique constraints are the
    cross-worker authority for both backends.
    """
    if db_backend.is_postgres():
        return await _create_public_vk_comment_inner(
            vk_actor_id, gen_id, comment_text, client_request_id,
        )
    async with _sqlite_writer_lock():
        return await _create_public_vk_comment_inner(
            vk_actor_id, gen_id, comment_text, client_request_id,
        )


async def _create_public_vk_comment_inner(
    vk_actor_id: int, gen_id: int, comment_text: str, client_request_id: str,
) -> dict | None:
    """Commit one VK-owned comment, returning a read-compatible card or None if private.

    The DB unique constraints protect both same-key replay and fast distinct
    keys across concurrent workers; no in-memory mutex is trusted.
    """
    if (type(vk_actor_id) is not int or not 0 < vk_actor_id < 2**63
        or type(gen_id) is not int or not 0 < gen_id < 2**63):
        raise ValueError("Invalid signed VK actor or publication")
    if type(comment_text) is not str:
        raise TypeError("Invalid comment text")
    normalized = " ".join(comment_text.split()).strip()
    if not 1 <= len(normalized) <= MAX_COMMENT_CHARS:
        raise ValueError("Comment length outside accepted range")
    if type(client_request_id) is not str or _KEY_RE.fullmatch(client_request_id) is None:
        raise ValueError("Invalid native comment request key")

    cooldown_bucket = int(time.time()) // _rate_seconds()
    # Also verify media availability and publication scope through the
    # canonical shared feed reader before attempting any mutation.
    card = await database.get_feed_generation_card(
        gen_id, viewer_user_id=None, include_unavailable=False,
    )
    if not card or card.get("publication_scope") != "feed":
        return None

    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """INSERT INTO vk_feed_comments
               (generation_id, vk_user_id, text, client_request_id, cooldown_bucket)
               SELECT id, ?, ?, ?, ? FROM generation_tasks
               WHERE id = ? AND type IN ('image', 'video')
                 AND status = 'completed' AND result_url IS NOT NULL
                 AND is_public_feed = 1 AND COALESCE(is_adult_content, 0) = 0
               ON CONFLICT DO NOTHING""",
            (vk_actor_id, normalized, client_request_id, cooldown_bucket, gen_id),
        )
        if cursor.rowcount not in (0, 1):
            await db.rollback()
            raise RuntimeError("Uncertain VK comment mutation")
        claim = await db.execute(
            """SELECT id, generation_id, vk_user_id, text, created_at
               FROM vk_feed_comments
               WHERE vk_user_id = ? AND client_request_id = ?""",
            (vk_actor_id, client_request_id),
        )
        row = await claim.fetchone()
        if row is None:
            await db.rollback()
            if cursor.rowcount == 1:
                raise RuntimeError("Native comment missing after successful insert")
            # Different key but the same actor/rate bucket was rejected.
            # If the post became private during a race, do not bypass its ACL.
            still_public = await database.get_feed_generation_card(
                gen_id, viewer_user_id=None, include_unavailable=False,
            )
            if not still_public or still_public.get("publication_scope") != "feed":
                return None
            raise VkCommentCooldown()
        if row["generation_id"] != gen_id or row["text"] != normalized:
            await db.rollback()
            raise VkCommentConflict()
        # Count both platforms in the same persisted store; do not rely on a
        # stale in-memory card or guessed counter.
        totals = await db.execute(
            """SELECT
                 (SELECT COUNT(*) FROM feed_comments WHERE generation_id = ?)
                 + (SELECT COUNT(*) FROM vk_feed_comments WHERE generation_id = ?)
                 AS total""",
            (gen_id, gen_id),
        )
        counted = await totals.fetchone()
        if counted is None:
            await db.rollback()
            raise RuntimeError("VK comment total unavailable")
        total = int(counted["total"])
        await db.commit()
    return {
        "comment": _native_comment_payload(row, viewer_vk_user_id=vk_actor_id),
        "comments_count": total,
    }
