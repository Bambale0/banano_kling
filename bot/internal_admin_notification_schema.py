from __future__ import annotations

import asyncio
import logging
import os

import psycopg

logger = logging.getLogger(__name__)

_SCHEMA_READY = False
_SCHEMA_LOCK: asyncio.Lock | None = None


def _schema_lock() -> asyncio.Lock:
    global _SCHEMA_LOCK
    if _SCHEMA_LOCK is None:
        _SCHEMA_LOCK = asyncio.Lock()
    return _SCHEMA_LOCK


async def ensure_internal_admin_notification_schema() -> None:
    """Create notification campaign tables once per process.

    DDL uses psycopg directly because the compatibility DB adapter deliberately
    skips generic CREATE TABLE statements. Internal routes call this only after
    private-network and HMAC verification; the background worker calls it at
    controlled bot startup.
    """

    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    async with _schema_lock():
        if _SCHEMA_READY:
            return

        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise RuntimeError("Notification campaigns require PostgreSQL DATABASE_URL")

        connection = await psycopg.AsyncConnection.connect(database_url)
        try:
            async with connection.cursor() as cursor:
                # Serialize additive DDL across worker processes at startup.
                await cursor.execute("SELECT pg_advisory_xact_lock(784203119)")
                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS notification_campaigns (
                        id BIGSERIAL PRIMARY KEY,
                        name TEXT NOT NULL,
                        channel TEXT NOT NULL DEFAULT 'telegram',
                        status TEXT NOT NULL DEFAULT 'draft',
                        segment JSONB NOT NULL,
                        message JSONB NOT NULL,
                        audience_count INTEGER NOT NULL DEFAULT 0,
                        queued_count INTEGER NOT NULL DEFAULT 0,
                        sent_count INTEGER NOT NULL DEFAULT 0,
                        failed_count INTEGER NOT NULL DEFAULT 0,
                        blocked_count INTEGER NOT NULL DEFAULT 0,
                        cancelled_count INTEGER NOT NULL DEFAULT 0,
                        created_by TEXT,
                        reason TEXT NOT NULL,
                        request_id TEXT,
                        idempotency_key TEXT UNIQUE,
                        scheduled_at TIMESTAMP,
                        started_at TIMESTAMP,
                        completed_at TIMESTAMP,
                        cancelled_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        CHECK (status IN (
                            'draft', 'scheduled', 'running', 'completed',
                            'cancelled', 'failed'
                        ))
                    )
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_notification_campaigns_status_created
                    ON notification_campaigns(status, created_at DESC, id DESC)
                    """
                )
                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS notification_deliveries (
                        id BIGSERIAL PRIMARY KEY,
                        campaign_id BIGINT NOT NULL
                            REFERENCES notification_campaigns(id) ON DELETE CASCADE,
                        user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
                        telegram_id BIGINT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'queued',
                        attempts INTEGER NOT NULL DEFAULT 0,
                        lease_until TIMESTAMP,
                        next_attempt_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_error TEXT,
                        telegram_message_id BIGINT,
                        sent_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(campaign_id, telegram_id),
                        CHECK (status IN (
                            'queued', 'sending', 'sent', 'failed',
                            'blocked', 'cancelled'
                        ))
                    )
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_notification_deliveries_claim
                    ON notification_deliveries(status, next_attempt_at, lease_until, id)
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_notification_deliveries_campaign_status
                    ON notification_deliveries(campaign_id, status)
                    """
                )
                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS notification_test_sends (
                        id BIGSERIAL PRIMARY KEY,
                        campaign_id BIGINT NOT NULL
                            REFERENCES notification_campaigns(id) ON DELETE CASCADE,
                        telegram_id BIGINT NOT NULL,
                        status TEXT NOT NULL,
                        telegram_message_id BIGINT,
                        error TEXT,
                        requested_by TEXT,
                        request_id TEXT,
                        idempotency_key TEXT UNIQUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                # Append-only attribution metadata; never store promo text in the audit.
                await cursor.execute("""
                    CREATE TABLE IF NOT EXISTS notification_promo_revisions (
                        campaign_id BIGINT NOT NULL REFERENCES notification_campaigns(id),
                        revision INTEGER NOT NULL CHECK (revision > 0),
                        admin_telegram_id BIGINT NOT NULL,
                        payload_hash TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(campaign_id, revision)
                    )
                """)
                # Additive promo extension: existing campaigns keep their status and payload.
                for column in (
                    "promo_version INTEGER NOT NULL DEFAULT 0",
                    "revision INTEGER NOT NULL DEFAULT 1",
                    "content_hash TEXT",
                    "tested_content_hash TEXT",
                    "tested_at TIMESTAMP",
                    "tested_by TEXT",
                    "test_run_key TEXT",
                    "test_summary JSONB",
                    "message_snapshot JSONB",
                ):
                    await cursor.execute(
                        f"ALTER TABLE notification_campaigns ADD COLUMN IF NOT EXISTS {column}"
                    )
                for column in (
                    "delivery_parts JSONB NOT NULL DEFAULT '[]'::jsonb",
                    "attempt_token TEXT",
                ):
                    await cursor.execute(
                        f"ALTER TABLE notification_deliveries ADD COLUMN IF NOT EXISTS {column}"
                    )
                # Migrate once; avoid rescanning delivery history at every restart.
                await cursor.execute("""
                    SELECT pg_get_constraintdef(oid) FROM pg_constraint
                    WHERE conrelid = 'notification_deliveries'::regclass
                      AND conname = 'notification_deliveries_status_check'
                """)
                definition = await cursor.fetchone()
                if not definition or "'uncertain'" not in definition[0]:
                    await cursor.execute(
                        "ALTER TABLE notification_deliveries "
                        "DROP CONSTRAINT IF EXISTS notification_deliveries_status_check"
                    )
                    await cursor.execute("""
                        ALTER TABLE notification_deliveries
                        ADD CONSTRAINT notification_deliveries_status_check CHECK (
                            status IN ('queued', 'sending', 'sent', 'failed', 'blocked',
                                       'cancelled', 'uncertain')
                        )
                    """)
                for column in (
                    "content_hash TEXT",
                    "test_run_key TEXT",
                    "message_snapshot JSONB",
                    "delivery_parts JSONB NOT NULL DEFAULT '[]'::jsonb",
                    "attempt_token TEXT",
                    "attempts INTEGER NOT NULL DEFAULT 0",
                    "lease_until TIMESTAMP",
                    "next_attempt_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                    "sent_at TIMESTAMP",
                    "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                ):
                    await cursor.execute(
                        f"ALTER TABLE notification_test_sends ADD COLUMN IF NOT EXISTS {column}"
                    )
                await cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_notification_test_sends_claim
                    ON notification_test_sends(status, next_attempt_at, lease_until, id)
                """)
            await connection.commit()
        except Exception:
            await connection.rollback()
            logger.exception("Failed to initialize notification campaign schema")
            raise
        finally:
            await connection.close()

        _SCHEMA_READY = True
