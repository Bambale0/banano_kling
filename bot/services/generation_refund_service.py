"""Atomic one-time refunds for failed paid generation launches."""

from __future__ import annotations

import logging
from typing import Any

from bot import database
from bot import db as db_backend
from bot.config import config

logger = logging.getLogger(__name__)

_MAX_REFUND_KEY_LENGTH = 200
_MAX_REASON_LENGTH = 500


async def _ensure_refund_schema(connection: db_backend.Connection) -> None:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS generation_credit_refunds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            refund_key TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            telegram_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    await connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_generation_credit_refunds_user_created
        ON generation_credit_refunds(user_id, created_at)
        """
    )


def _normalize_refund_key(value: Any) -> str:
    return str(value or "").strip()[:_MAX_REFUND_KEY_LENGTH]


def _normalize_reason(value: Any) -> str:
    return str(value or "").strip()[:_MAX_REASON_LENGTH]


async def refund_generation_credits_once(
    telegram_id: int,
    amount: float,
    *,
    refund_key: str,
    reason: str = "",
) -> bool:
    """Credit one generation refund exactly once for a stable operation key."""
    normalized_key = _normalize_refund_key(refund_key)
    normalized_reason = _normalize_reason(reason)
    numeric_amount = float(amount or 0)

    if telegram_id <= 0 or numeric_amount <= 0 or not normalized_key:
        logger.warning(
            "Generation refund rejected: telegram_id=%s amount=%s has_key=%s",
            telegram_id,
            numeric_amount,
            bool(normalized_key),
        )
        return False

    if config.is_admin(telegram_id):
        logger.info(
            "Generation refund skipped for admin: telegram_id=%s key=%s",
            telegram_id,
            normalized_key,
        )
        return False

    async with db_backend.connect(database.DATABASE_PATH) as connection:
        connection.row_factory = db_backend.Row
        await connection.execute("BEGIN IMMEDIATE")
        await _ensure_refund_schema(connection)

        cursor = await connection.execute(
            "SELECT id FROM users WHERE telegram_id = ? LIMIT 1",
            (telegram_id,),
        )
        user = await cursor.fetchone()
        if not user:
            await connection.rollback()
            logger.warning(
                "Generation refund user not found: telegram_id=%s key=%s",
                telegram_id,
                normalized_key,
            )
            return False

        cursor = await connection.execute(
            """
            INSERT OR IGNORE INTO generation_credit_refunds (
                refund_key, user_id, telegram_id, amount, reason
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                normalized_key,
                int(user["id"]),
                telegram_id,
                numeric_amount,
                normalized_reason,
            ),
        )
        if int(getattr(cursor, "rowcount", 0) or 0) != 1:
            await connection.rollback()
            logger.info(
                "Generation refund already applied: telegram_id=%s key=%s",
                telegram_id,
                normalized_key,
            )
            return False

        cursor = await connection.execute(
            """
            UPDATE users
            SET credits = credits + ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (numeric_amount, int(user["id"])),
        )
        if int(getattr(cursor, "rowcount", 0) or 0) != 1:
            await connection.rollback()
            logger.error(
                "Generation refund balance update failed: telegram_id=%s key=%s",
                telegram_id,
                normalized_key,
            )
            return False

        await connection.commit()

    logger.info(
        "Generation refund applied: telegram_id=%s amount=%s key=%s reason=%s",
        telegram_id,
        numeric_amount,
        normalized_key,
        normalized_reason,
    )
    return True
