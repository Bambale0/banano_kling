from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot

from bot import db as db_backend
from bot.config import config
from bot.database import DATABASE_PATH, get_or_create_user

logger = logging.getLogger(__name__)

PARTNER_APPLICATION_AVAILABLE = "available"
PARTNER_APPLICATION_PENDING = "pending"
PARTNER_APPLICATION_APPROVED = "approved"
PARTNER_APPLICATION_REJECTED = "rejected"
PARTNER_MANUAL_APPROVAL_CUTOFF = os.getenv(
    "PARTNER_MANUAL_APPROVAL_CUTOFF",
    "2026-08-08T13:44:22",
).strip()

_SCHEMA_READY = False
_SCHEMA_LOCK: asyncio.Lock | None = None


def _as_utc_naive_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            logger.error("Invalid partner approval datetime: %r", value)
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def is_legacy_partner_registration(created_at: Any) -> bool:
    """Return whether the account predates mandatory manual partner approval."""

    created = _as_utc_naive_datetime(created_at)
    cutoff = _as_utc_naive_datetime(PARTNER_MANUAL_APPROVAL_CUTOFF)
    return bool(created and cutoff and created < cutoff)


def _schema_lock() -> asyncio.Lock:
    global _SCHEMA_LOCK
    if _SCHEMA_LOCK is None:
        _SCHEMA_LOCK = asyncio.Lock()
    return _SCHEMA_LOCK


def _postgres_dsn() -> str:
    dsn = str(os.getenv("DATABASE_URL", "") or "").strip()
    if dsn.lower().startswith("postgresql+asyncpg://"):
        return "postgresql://" + dsn[len("postgresql+asyncpg://") :]
    return dsn


async def ensure_partner_approval_schema() -> None:
    """Keep legacy application storage available for read-only history."""

    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    async with _schema_lock():
        if _SCHEMA_READY:
            return

        if db_backend.is_postgres():
            import psycopg

            dsn = _postgres_dsn()
            if not dsn:
                raise RuntimeError("DATABASE_URL is required for PostgreSQL")
            async with await psycopg.AsyncConnection.connect(dsn) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS partner_applications (
                            id BIGSERIAL PRIMARY KEY,
                            user_id BIGINT NOT NULL UNIQUE REFERENCES users(id),
                            status TEXT NOT NULL DEFAULT 'pending',
                            source TEXT,
                            requested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            reviewed_at TIMESTAMP,
                            reviewed_by_telegram_id BIGINT,
                            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                    await cur.execute(
                        "CREATE INDEX IF NOT EXISTS idx_partner_applications_status_requested "
                        "ON partner_applications(status, requested_at DESC)"
                    )
                    await conn.commit()
        else:
            async with db_backend.connect(DATABASE_PATH) as db:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS partner_applications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL UNIQUE,
                        status TEXT NOT NULL DEFAULT 'pending',
                        source TEXT,
                        requested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        reviewed_at TIMESTAMP,
                        reviewed_by_telegram_id INTEGER,
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id)
                    )
                    """
                )
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_partner_applications_status_requested "
                    "ON partner_applications(status, requested_at DESC)"
                )
                await db.commit()

        _SCHEMA_READY = True


def _application_payload(row: Any | None) -> dict[str, Any] | None:
    if not row:
        return None
    keys = set(row.keys())
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "telegram_id": int(row["telegram_id"]) if "telegram_id" in keys else None,
        "username": (row["username"] or "") if "username" in keys else "",
        "first_name": (row["first_name"] or "") if "first_name" in keys else "",
        "last_name": (row["last_name"] or "") if "last_name" in keys else "",
        "referral_code": (row["referral_code"] or "") if "referral_code" in keys else "",
        "status": str(row["status"] or PARTNER_APPLICATION_PENDING),
        "source": (row["source"] or "") if "source" in keys else "",
        "requested_at": row["requested_at"] if "requested_at" in keys else None,
        "reviewed_at": row["reviewed_at"] if "reviewed_at" in keys else None,
        "reviewed_by_telegram_id": (
            int(row["reviewed_by_telegram_id"])
            if "reviewed_by_telegram_id" in keys and row["reviewed_by_telegram_id"]
            else None
        ),
    }


async def get_partner_application_state(telegram_id: int) -> dict[str, Any]:
    """Return open partner eligibility and read-only historical application data.

    ``approved`` remains the legacy API value for an accessible cabinet. It is
    not a moderation decision or evidence that an agreement was accepted.
    """

    await ensure_partner_approval_schema()
    user = await get_or_create_user(int(telegram_id))
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT id, status, requested_at, reviewed_at
            FROM partner_applications
            WHERE user_id = ?
            LIMIT 1
            """,
            (user.id,),
        )
        row = await cursor.fetchone()

    return {
        "status": PARTNER_APPLICATION_APPROVED,
        "is_partner": True,
        "is_legacy": is_legacy_partner_registration(user.created_at)
        and not bool(user.partner_agreed_at),
        "application_id": int(row["id"]) if row else None,
        "application_status": str(row["status"]) if row else None,
        "can_apply": False,
        "requested_at": row["requested_at"] if row else None,
        "reviewed_at": row["reviewed_at"] if row else None,
    }


async def get_partner_application(application_id: int) -> dict[str, Any] | None:
    await ensure_partner_approval_schema()
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT pa.id, pa.user_id, pa.status, pa.source, pa.requested_at,
                   pa.reviewed_at, pa.reviewed_by_telegram_id,
                   u.telegram_id, u.username, u.first_name, u.last_name,
                   u.referral_code
            FROM partner_applications pa
            JOIN users u ON u.id = pa.user_id
            WHERE pa.id = ?
            LIMIT 1
            """,
            (int(application_id),),
        )
        return _application_payload(await cursor.fetchone())


async def count_pending_partner_applications() -> int:
    """Return the total number of pending partner applications."""

    await ensure_partner_approval_schema()
    async with db_backend.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM partner_applications WHERE status = 'pending'"
        )
        row = await cursor.fetchone()
        if row is None:
            return 0
        return int(row[0])


async def get_pending_partner_applications(
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return pending partner applications for the admin review queue."""

    await ensure_partner_approval_schema()
    safe_limit = max(1, min(int(limit or 20), 100))
    safe_offset = max(0, int(offset or 0))
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT pa.id, pa.user_id, pa.status, pa.source, pa.requested_at,
                   pa.reviewed_at, pa.reviewed_by_telegram_id,
                   u.telegram_id, u.username, u.first_name, u.last_name,
                   u.referral_code
            FROM partner_applications pa
            JOIN users u ON u.id = pa.user_id
            WHERE pa.status = 'pending'
            ORDER BY pa.requested_at ASC, pa.id ASC
            LIMIT ? OFFSET ?
            """,
            (safe_limit, safe_offset),
        )
        return [
            payload
            for row in await cursor.fetchall()
            if (payload := _application_payload(row)) is not None
        ]


async def submit_partner_application(
    telegram_id: int,
    *,
    source: str,
) -> dict[str, Any]:
    """Compatibility entry point for old clients; no application is required.

    Never insert applications or synthesize consent when a stale activation
    button is pressed. Existing application and agreement records stay intact.
    """

    state = await get_partner_application_state(telegram_id)
    return {"ok": True, "created": False, **state}


async def review_partner_application(
    application_id: int,
    *,
    approve: bool,
    admin_telegram_id: int,
) -> dict[str, Any]:
    """Keep old admin review calls authorized and historical records read-only."""

    if not config.is_admin(int(admin_telegram_id)):
        return {"ok": False, "reason": "forbidden"}
    application = await get_partner_application(int(application_id))
    if application is None:
        return {"ok": False, "reason": "not_found"}
    return {
        "ok": False,
        "reason": "activation_not_required",
        "status": application["status"],
        "application": application,
    }


async def notify_admins_about_partner_application(
    bot: Bot | None,
    application_id: int,
) -> None:
    """Retired compatibility hook: never send new activation requests."""


async def notify_user_about_partner_review(
    bot: Bot | None,
    application: dict[str, Any] | None,
    *,
    approved: bool,
) -> None:
    """Retired compatibility hook: historical verdicts do not alter access."""


def install_partner_referral_approval_guard() -> None:
    """Compatibility no-op; the canonical referral service owns all safeguards.

    Partner activation no longer restricts attribution. Do not wrap or replace
    referral handlers: their ban, self-referral, cycle and replay checks remain.
    """
