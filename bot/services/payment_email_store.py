from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATABASE_PATH = _REPO_ROOT / "data" / "payment-emails.sqlite3"
DATABASE_PATH = Path(
    os.getenv("PAYMENT_EMAIL_DATABASE_PATH", str(_DEFAULT_DATABASE_PATH))
).expanduser()

_SCHEMA_READY = False
_SCHEMA_LOCK: asyncio.Lock | None = None


def _get_schema_lock() -> asyncio.Lock:
    global _SCHEMA_LOCK
    if _SCHEMA_LOCK is None:
        _SCHEMA_LOCK = asyncio.Lock()
    return _SCHEMA_LOCK


def _harden_path_permissions() -> None:
    """Restrict the local payment data directory and database to the service user."""

    try:
        DATABASE_PATH.parent.chmod(0o700)
    except OSError:
        logger.warning("Could not restrict payment email directory permissions")

    for path in (
        DATABASE_PATH,
        Path(f"{DATABASE_PATH}-wal"),
        Path(f"{DATABASE_PATH}-shm"),
    ):
        if not path.exists():
            continue
        try:
            path.chmod(0o600)
        except OSError:
            logger.warning("Could not restrict payment email database permissions")


async def ensure_schema() -> None:
    """Create the server-local storage used only for payment contact data."""

    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    async with _get_schema_lock():
        if _SCHEMA_READY:
            return

        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _harden_path_permissions()
        async with aiosqlite.connect(DATABASE_PATH, timeout=30) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA synchronous=FULL")
            await db.execute("PRAGMA busy_timeout=30000")
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS payment_customer_profiles (
                    telegram_id INTEGER PRIMARY KEY,
                    email TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.commit()

        _harden_path_permissions()
        _SCHEMA_READY = True


async def get_payment_email(telegram_id: int) -> str | None:
    await ensure_schema()
    async with aiosqlite.connect(DATABASE_PATH, timeout=30) as db:
        cursor = await db.execute(
            "SELECT email FROM payment_customer_profiles WHERE telegram_id = ? LIMIT 1",
            (int(telegram_id),),
        )
        row = await cursor.fetchone()
    if not row:
        return None
    value = str(row[0] or "").strip().lower()
    return value or None


async def has_payment_email(telegram_id: int) -> bool:
    return bool(await get_payment_email(telegram_id))


async def save_payment_email(telegram_id: int, email: str) -> str:
    normalized = str(email or "").strip().lower()
    if not normalized:
        raise ValueError("Payment email is required")

    await ensure_schema()
    async with aiosqlite.connect(DATABASE_PATH, timeout=30) as db:
        await db.execute(
            """
            INSERT INTO payment_customer_profiles (
                telegram_id,
                email,
                updated_at
            )
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_id) DO UPDATE SET
                email = excluded.email,
                updated_at = CURRENT_TIMESTAMP
            """,
            (int(telegram_id), normalized),
        )
        await db.commit()

    _harden_path_permissions()
    return normalized
