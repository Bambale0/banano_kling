"""Append-only, transactional history for the editorial trend showcase.

Contains only category metadata, trend IDs, ordering and badge settings.
Never include the executable trend prompt, private reference URLs or user media.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from bot import db as db_backend

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS trend_catalog_audit (
        id TEXT PRIMARY KEY,
        actor_telegram_id BIGINT NOT NULL,
        action TEXT NOT NULL,
        category_id BIGINT,
        trend_id BIGINT,
        before_state TEXT NOT NULL,
        after_state TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE INDEX IF NOT EXISTS idx_trend_catalog_audit_category
        ON trend_catalog_audit(category_id, created_at)""",
    """CREATE INDEX IF NOT EXISTS idx_trend_catalog_audit_actor
        ON trend_catalog_audit(actor_telegram_id, created_at)""",
)
PG_GUARD = (
    """CREATE OR REPLACE FUNCTION trend_catalog_audit_append_only()
       RETURNS trigger LANGUAGE plpgsql AS $$
       BEGIN RAISE EXCEPTION 'trend catalog audit is append-only'; END;
       $$""",
    """DO $$ BEGIN
       IF NOT EXISTS (
           SELECT 1 FROM pg_trigger
           WHERE tgname = 'trend_catalog_audit_append_only_guard'
             AND tgrelid = 'trend_catalog_audit'::regclass
       ) THEN
           CREATE TRIGGER trend_catalog_audit_append_only_guard
           BEFORE UPDATE OR DELETE OR TRUNCATE ON trend_catalog_audit
           FOR EACH STATEMENT EXECUTE FUNCTION trend_catalog_audit_append_only();
       END IF;
       END $$""",
)


async def ensure_schema(db: Any) -> None:
    """Additive migration; re-entry cannot erase the recorded history."""
    ddl = getattr(db, "execute_native_ddl", db.execute)
    for statement in SCHEMA:
        await ddl(statement)
    if db_backend.is_postgres():
        for statement in PG_GUARD:
            await ddl(statement)
    else:
        for command in ("UPDATE", "DELETE"):
            await ddl(
                "CREATE TRIGGER IF NOT EXISTS trend_catalog_audit_no_"
                + command.lower()
                + " BEFORE "
                + command
                + " ON trend_catalog_audit BEGIN "
                "SELECT RAISE(ABORT, 'trend catalog audit is append-only'); END"
            )


async def category_snapshot(
    db: Any, category_id: int, *, include_items: bool = False
) -> dict[str, Any] | None:
    row = await (
        await db.execute(
            """SELECT id, title, emoji, sort_order, is_visible, revision
               FROM trend_categories WHERE id = ?""",
            (category_id,),
        )
    ).fetchone()
    if row is None:
        return None
    result: dict[str, Any] = {
        "id": int(row[0]),
        "title": str(row[1]),
        "emoji": str(row[2] or ""),
        "sort_order": int(row[3]),
        "is_visible": bool(row[4]),
        "revision": int(row[5]),
    }
    if include_items:
        rows = await (
            await db.execute(
                """SELECT prompt_id, sort_order, badge, badge_until
                   FROM trend_category_items WHERE category_id = ?
                   ORDER BY sort_order ASC, prompt_id ASC""",
                (category_id,),
            )
        ).fetchall()
        result["items"] = [
            {
                "prompt_id": int(item[0]),
                "sort_order": int(item[1]),
                "badge": str(item[2] or ""),
                "badge_until": str(item[3]) if item[3] else None,
            }
            for item in rows
        ]
    return result


async def categories_snapshot(db: Any) -> list[dict[str, Any]]:
    rows = await (
        await db.execute(
            """SELECT id, title, emoji, sort_order, is_visible, revision
               FROM trend_categories ORDER BY sort_order ASC, id ASC"""
        )
    ).fetchall()
    return [
        {
            "id": int(row[0]),
            "title": str(row[1]),
            "emoji": str(row[2] or ""),
            "sort_order": int(row[3]),
            "is_visible": bool(row[4]),
            "revision": int(row[5]),
        }
        for row in rows
    ]


async def memberships_snapshot(db: Any, trend_id: int) -> dict[str, Any]:
    rows = await (
        await db.execute(
            """SELECT ti.category_id, ti.sort_order, ti.badge, ti.badge_until,
                      c.revision
               FROM trend_category_items ti
               JOIN trend_categories c ON c.id = ti.category_id
               WHERE ti.prompt_id = ?
               ORDER BY ti.category_id ASC""",
            (trend_id,),
        )
    ).fetchall()
    return {
        "trend_id": int(trend_id),
        "placements": [
            {
                "category_id": int(row[0]),
                "sort_order": int(row[1]),
                "badge": str(row[2] or ""),
                "badge_until": str(row[3]) if row[3] else None,
                "category_revision": int(row[4]),
            }
            for row in rows
        ],
    }


async def append(
    db: Any,
    *,
    actor_id: int,
    action: str,
    category_id: int | None = None,
    trend_id: int | None = None,
    before: Any,
    after: Any,
) -> str:
    """Use the SAME connection and transaction as the corresponding mutation."""
    if type(actor_id) is not int or actor_id < 0 or actor_id >= 2**63:
        raise ValueError("Invalid audit actor")
    if not action or len(action) > 64:
        raise ValueError("Invalid audit action")
    event_id = uuid4().hex
    before_json = json.dumps(
        before, ensure_ascii=False, sort_keys=True, allow_nan=False
    )
    after_json = json.dumps(after, ensure_ascii=False, sort_keys=True, allow_nan=False)
    # SQLite's CURRENT_TIMESTAMP is second-granular; preserve microseconds
    # so rapid successive edits can be reconstructed in the admin history.
    created_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
    await db.execute(
        """INSERT INTO trend_catalog_audit
           (id, actor_telegram_id, action, category_id, trend_id,
            before_state, after_state, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event_id,
            actor_id,
            action,
            category_id,
            trend_id,
            before_json,
            after_json,
            created_at,
        ),
    )
    return event_id


async def list_history(*, limit: int = 30) -> list[dict[str, Any]]:
    """Admin-only caller. Never return this list through the public catalog."""
    from bot import database

    safe_limit = min(100, max(1, int(limit)))
    async with db_backend.connect(database.DATABASE_PATH) as db:
        rows = await (
            await db.execute(
                """SELECT id, actor_telegram_id, action, category_id, trend_id,
                          before_state, after_state, created_at
                   FROM trend_catalog_audit ORDER BY created_at DESC, id DESC LIMIT ?""",
                (safe_limit,),
            )
        ).fetchall()
    return [
        {
            "id": str(row[0]),
            "actor_telegram_id": int(row[1]),
            "action": str(row[2]),
            "category_id": int(row[3]) if row[3] is not None else None,
            "trend_id": int(row[4]) if row[4] is not None else None,
            "before": json.loads(row[5]),
            "after": json.loads(row[6]),
            "created_at": str(row[7]),
        }
        for row in rows
    ]
