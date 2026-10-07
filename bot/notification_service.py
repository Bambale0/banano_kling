from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import time
from typing import Any
from uuid import uuid4

from aiogram import Bot

from bot import db as db_backend
from bot.config import config
from bot.internal_admin_notification_schema import (
    ensure_internal_admin_notification_schema,
)
from bot.internal_admin_notifications import _decode_json_object, send_campaign_message
from bot.promo_message import (
    REQUEST_TIMEOUT_SECONDS,
    DeliveryLeaseLost,
    DeliveryPartError,
    PromoMessageValidationError,
    SendResult,
    classify_delivery_error,
    deliver_message_snapshot,
)

logger = logging.getLogger(__name__)

POLL_SECONDS = 1.0
LEASE_SECONDS = 90
MAX_ATTEMPTS = 5
BATCH_DELAY_SECONDS = 0.05
_WORKER_TASK: asyncio.Task[None] | None = None
assert REQUEST_TIMEOUT_SECONDS < LEASE_SECONDS


def _table(item: dict[str, Any]) -> str:
    return (
        "notification_test_sends" if item.get("is_test") else "notification_deliveries"
    )


def _parts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError) as exc:
            raise DeliveryPartError("uncertain", "invalid_saved_progress") from exc
    if value is None:
        return []
    if not isinstance(value, list):
        raise DeliveryPartError("uncertain", "invalid_saved_progress")
    return copy.deepcopy(value)


def _admin_ids() -> list[int]:
    return sorted({int(item) for item in config.admin_ids if int(item) > 0})


async def _recover_table(*, is_test: bool) -> int:
    table = "notification_test_sends" if is_test else "notification_deliveries"
    error_column = "error" if is_test else "last_error"
    # If every receipt was committed, a crash before the final status update is
    # recoverable without calling Telegram. Only pending/retryable parts replay.
    all_sent = """(jsonb_array_length(d.delivery_parts) > 0 AND NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(d.delivery_parts) p
        WHERE p->>'status' IS DISTINCT FROM 'sent'
    ))"""
    # Every fenced sender commits part intent before calling Telegram. An empty
    # progress list on a new fenced claim proves this claim made no API attempt.
    unstarted = """(jsonb_array_length(d.delivery_parts) = 0
        AND d.attempt_token IS NOT NULL)"""
    unsafe = """((jsonb_array_length(d.delivery_parts) = 0 AND d.attempt_token IS NULL)
        OR EXISTS (SELECT 1 FROM jsonb_array_elements(d.delivery_parts) p
                   WHERE COALESCE(p->>'status', '') NOT IN ('sent', 'pending', 'retryable')))"""
    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(
            f"""
            UPDATE {table} d
            SET status = CASE WHEN {all_sent} THEN 'sent'
                              WHEN {unsafe} THEN 'uncertain' ELSE 'failed' END,
                attempts = CASE WHEN {unstarted} THEN GREATEST(d.attempts - 1, 0)
                                ELSE d.attempts END,
                telegram_message_id = CASE WHEN {all_sent}
                    THEN (d.delivery_parts->-1->'message_ids'->>-1)::bigint
                    ELSE d.telegram_message_id END,
                sent_at = CASE WHEN {all_sent} THEN COALESCE(d.sent_at, CURRENT_TIMESTAMP)
                               ELSE d.sent_at END,
                lease_until = NULL, attempt_token = NULL,
                next_attempt_at = GREATEST(
                    CURRENT_TIMESTAMP,
                    d.updated_at + COALESCE((
                        SELECT MAX((p->>'retry_after')::integer)
                        FROM jsonb_array_elements(d.delivery_parts) p
                        WHERE p->>'status' = 'retryable'
                    ), 0) * INTERVAL '1 second'
                ),
                {error_column} = CASE WHEN {all_sent} THEN NULL
                    WHEN {unstarted} THEN 'delivery lease expired before API intent'
                    WHEN {unsafe} THEN 'unconfirmed_previous_attempt [reconciliation-required]'
                    ELSE 'delivery lease expired before next part' END,
                updated_at = CURRENT_TIMESTAMP
            WHERE d.status = 'sending'
              AND d.lease_until < CURRENT_TIMESTAMP
              {"AND d.test_run_key IS NOT NULL" if is_test else ""}
            RETURNING d.campaign_id
            """
        )
        recovered = int(cursor.rowcount or 0)
        rows = await cursor.fetchall() if recovered else []
        await connection.commit()
    for campaign_id in {int(row["campaign_id"]) for row in rows}:
        if is_test:
            from bot.promo_campaigns import refresh_test_state

            await refresh_test_state(campaign_id, None)
        else:
            await _refresh_campaign(campaign_id)
    return recovered


async def _recover_expired_leases() -> int:
    return await _recover_table(is_test=False)


async def _recover_expired_test_leases() -> int:
    return await _recover_table(is_test=True)


async def _cancel_obsolete_tests() -> None:
    admins = _admin_ids()
    revoked = (
        f"t.telegram_id NOT IN ({','.join('?' for _ in admins)})" if admins else "TRUE"
    )
    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(
            f"""
            UPDATE notification_test_sends t
            SET status = 'cancelled', attempt_token = NULL, lease_until = NULL,
                error = CASE WHEN {revoked} THEN 'test_recipient_no_longer_admin'
                             ELSE 'obsolete_test_version' END,
                updated_at = CURRENT_TIMESTAMP
            FROM notification_campaigns c
            WHERE c.id = t.campaign_id AND t.test_run_key IS NOT NULL
              AND t.status IN ('queued', 'failed')
              AND (c.status NOT IN ('draft', 'running', 'completed') OR t.test_run_key IS DISTINCT FROM c.test_run_key
                   OR t.content_hash IS DISTINCT FROM c.content_hash OR {revoked})
            RETURNING t.campaign_id
            """,
            tuple(admins + admins),
        )
        rows = await cursor.fetchall()
        await connection.commit()
    for campaign_id in {int(row["campaign_id"]) for row in rows}:
        from bot.promo_campaigns import refresh_test_state

        await refresh_test_state(campaign_id, None)


async def _claim(*, is_test: bool) -> dict[str, Any] | None:
    table = "notification_test_sends" if is_test else "notification_deliveries"
    admins = _admin_ids() if is_test else []
    if is_test and not admins:
        return None
    # TIMESTAMP columns and comparisons use the PostgreSQL session timezone.
    # Derive deadlines from that same database clock, never naive client UTC.
    token = uuid4().hex
    condition = "c.status = 'running'"
    parameters: list[Any] = [MAX_ATTEMPTS]
    snapshot = "c.message_snapshot"
    if is_test:
        condition = (
            "c.status IN ('draft', 'running', 'completed') AND d.test_run_key = c.test_run_key "
            "AND d.content_hash = c.content_hash "
            f"AND d.telegram_id IN ({','.join('?' for _ in admins)})"
        )
        parameters.extend(admins)
        snapshot = "d.message_snapshot"
    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(
            f"""
            SELECT d.id, d.campaign_id, d.telegram_id, d.attempts, d.delivery_parts,
                   {snapshot} AS message_snapshot, c.message,
                   {"d.content_hash" if is_test else "c.content_hash"} AS content_hash,
                   c.status AS campaign_status
            FROM {table} d
            JOIN notification_campaigns c ON c.id = d.campaign_id
            WHERE d.status IN ('queued', 'failed')
              AND d.next_attempt_at <= CURRENT_TIMESTAMP AND d.attempts < ?
              AND {condition}
            ORDER BY d.id
            FOR UPDATE OF d SKIP LOCKED
            LIMIT 1
            """,
            tuple(parameters),
        )
        row = await cursor.fetchone()
        if not row:
            await connection.rollback()
            return None
        await connection.execute(
            f"""
            UPDATE {table}
            SET status = 'sending', attempts = attempts + 1,
                lease_until = CURRENT_TIMESTAMP + (? * INTERVAL '1 second'), attempt_token = ?,
                {"error" if is_test else "last_error"} = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (LEASE_SECONDS, token, row["id"]),
        )
        await connection.commit()
    item = dict(row)
    item.update(
        attempts=int(item["attempts"] or 0) + 1, attempt_token=token, is_test=is_test
    )
    return item


async def _claim_delivery() -> dict[str, Any] | None:
    return await _claim(is_test=False)


async def _claim_test_delivery() -> dict[str, Any] | None:
    return await _claim(is_test=True)


async def _save_progress(item: dict[str, Any], progress: list[dict[str, Any]]) -> None:
    table = _table(item)
    condition = "c.status = 'running'"
    parameters: list[Any] = [
        json.dumps(progress, ensure_ascii=False),
        LEASE_SECONDS,
        int(item["id"]),
        item["attempt_token"],
    ]
    if item.get("is_test"):
        admins = _admin_ids()
        if int(item["telegram_id"]) not in admins:
            raise DeliveryLeaseLost("test recipient is no longer an administrator")
        condition = (
            "c.status IN ('draft', 'running', 'completed') AND d.test_run_key = c.test_run_key "
            "AND d.content_hash = c.content_hash"
        )
    async with db_backend.connect() as connection:
        cursor = await connection.execute(
            f"""
            UPDATE {table} d
            SET delivery_parts = ?::jsonb,
                lease_until = CURRENT_TIMESTAMP + (? * INTERVAL '1 second'),
                updated_at = CURRENT_TIMESTAMP
            FROM notification_campaigns c
            WHERE d.id = ? AND d.attempt_token = ? AND d.status = 'sending'
              AND d.lease_until > CURRENT_TIMESTAMP
              AND c.id = d.campaign_id AND {condition}
            """,
            tuple(parameters),
        )
        if cursor.rowcount != 1:
            await connection.rollback()
            raise DeliveryLeaseLost("delivery lease or campaign version changed")
        await connection.commit()
    item["delivery_parts"] = copy.deepcopy(progress)


async def _finish(
    item: dict[str, Any],
    *,
    status: str,
    message_id: int | None = None,
    error: DeliveryPartError | None = None,
) -> None:
    terminal = error is not None and (
        error.kind == "terminal" or int(item["attempts"]) >= MAX_ATTEMPTS
    )
    delay = (
        error.retry_after
        if error is not None and error.retry_after is not None
        else min(15 * 60, 5 * (2 ** max(int(item["attempts"]) - 1, 0)))
    )
    error_text = (
        None
        if error is None
        else error.error_code
        + (
            " [reconciliation-required]"
            if error.kind == "uncertain"
            else " [dead-letter]"
            if terminal
            else ""
        )
    )
    async with db_backend.connect() as connection:
        cursor = await connection.execute(
            f"""
            UPDATE {_table(item)}
            SET status = ?, telegram_message_id = COALESCE(?, telegram_message_id),
                sent_at = CASE WHEN ? = 'sent' THEN CURRENT_TIMESTAMP ELSE sent_at END,
                attempts = CASE WHEN ? THEN ? ELSE attempts END,
                lease_until = NULL, attempt_token = NULL,
                next_attempt_at = CURRENT_TIMESTAMP + (? * INTERVAL '1 second'),
                {"error" if item.get("is_test") else "last_error"} = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND attempt_token = ? AND status = 'sending'
              AND lease_until > CURRENT_TIMESTAMP
            """,
            (
                status,
                message_id,
                status,
                terminal,
                MAX_ATTEMPTS,
                max(1, delay),
                error_text,
                int(item["id"]),
                item["attempt_token"],
            ),
        )
        if cursor.rowcount != 1:
            await connection.rollback()
            raise DeliveryLeaseLost("delivery completion lost its lease")
        await connection.commit()


async def _mark_failed(
    delivery_id: int,
    attempts: int,
    error: Exception,
    *,
    attempt_token: str | None = None,
) -> None:
    """Compatibility seam; workers always provide a fencing token through _finish."""
    if attempt_token is not None:
        await _finish(
            {"id": delivery_id, "attempts": attempts, "attempt_token": attempt_token},
            status="failed",
            error=classify_delivery_error(error),
        )
        return
    # Retained for older internal callers; cannot change an actively owned row.
    code = type(error).__name__ + (" [dead-letter]" if attempts >= MAX_ATTEMPTS else "")
    delay = getattr(error, "retry_after", None) or min(
        900, 5 * (2 ** max(attempts - 1, 0))
    )
    async with db_backend.connect() as connection:
        await connection.execute(
            """
            UPDATE notification_deliveries SET status = ?,
                next_attempt_at = CURRENT_TIMESTAMP + (? * INTERVAL '1 second'), last_error = ?,
                updated_at = CURRENT_TIMESTAMP WHERE id = ? AND attempt_token IS NULL
            """,
            (
                "failed",
                delay,
                code,
                delivery_id,
            ),
        )
        await connection.commit()


async def _deliver_legacy(
    bot: Bot, item: dict[str, Any], message: dict[str, Any]
) -> SendResult:
    """Keep legacy payload semantics, adding the same receipt-before-replay safety."""
    progress = _parts(item.get("delivery_parts"))
    fingerprint = hashlib.sha256(
        json.dumps(message, sort_keys=True).encode()
    ).hexdigest()
    if progress:
        if len(progress) != 1 or progress[0].get("part_hash") != fingerprint:
            raise DeliveryPartError("uncertain", "legacy_progress_mismatch")
        state = progress[0]
        if state.get("status") == "sent":
            ids = state.get("message_ids")
            if (
                isinstance(ids, list)
                and len(ids) == 1
                and type(ids[0]) is int
                and ids[0] > 0
            ):
                return SendResult(ids[0], ids)
            raise DeliveryPartError("uncertain", "missing_confirmed_receipt")
        if state.get("status") not in {"pending", "retryable"}:
            raise DeliveryPartError("uncertain", "unconfirmed_previous_attempt")
    else:
        progress = [
            {
                "index": 0,
                "part_hash": fingerprint,
                "status": "pending",
                "message_ids": [],
                "attempts": 0,
            }
        ]
        state = progress[0]
    state.update(status="sending", attempts=int(state["attempts"]) + 1, message_ids=[])
    await _save_progress(item, progress)
    try:
        sent = await asyncio.wait_for(
            send_campaign_message(bot, int(item["telegram_id"]), message),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        message_id = sent.message_id
        if type(message_id) is not int or message_id <= 0:
            raise DeliveryPartError("uncertain", "invalid_receipt")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        error = classify_delivery_error(exc)
        state.update(status=error.kind, error_code=error.error_code)
        if error.retry_after is not None:
            state["retry_after"] = error.retry_after
        await _save_progress(item, progress)
        raise error from exc
    state.update(status="sent", message_ids=[message_id])
    await _save_progress(item, progress)
    return SendResult(message_id, [message_id])


async def process_delivery(bot: Bot, item: dict[str, Any]) -> None:
    """Process a claimed row; SQL ownership checks gate every network side effect."""
    started = time.monotonic()
    snapshot = _decode_json_object(item.get("message_snapshot"))
    message = snapshot.get("message") or _decode_json_object(item.get("message"))
    buttons = message.get("buttons") or []
    trend_ids = [
        button.get("trend_id") for button in buttons if isinstance(button, dict)
    ]
    logger.info(
        "Notification delivery started; campaign_id=%s delivery_id=%s telegram_id=%s "
        "test=%s attempt=%s content_hash=%s button_count=%s trend_ids=%s",
        item["campaign_id"],
        item["id"],
        item["telegram_id"],
        item.get("is_test", False),
        item["attempts"],
        item.get("content_hash"),
        len(buttons),
        trend_ids,
    )
    try:
        if snapshot:
            if snapshot.get("content_hash") != item.get("content_hash"):
                raise PromoMessageValidationError("campaign snapshot hash changed")

            async def save_progress(parts):
                await _save_progress(item, parts)

            result = await deliver_message_snapshot(
                bot,
                int(item["telegram_id"]),
                snapshot,
                delivery_parts=_parts(item.get("delivery_parts")),
                save_progress=save_progress,
            )
        else:
            message = _decode_json_object(item.get("message"))
            if item.get("is_test") or message.get("schema_version") == 2:
                raise PromoMessageValidationError(
                    "immutable message snapshot is missing"
                )
            result = await _deliver_legacy(bot, item, message)
        await _finish(item, status="sent", message_id=result.message_id)
        logger.info(
            "Notification delivery sent; campaign_id=%s delivery_id=%s telegram_id=%s "
            "test=%s attempt=%s content_hash=%s duration_ms=%.1f message_count=%s "
            "telegram_message_id=%s",
            item["campaign_id"],
            item["id"],
            item["telegram_id"],
            item.get("is_test", False),
            item["attempts"],
            item.get("content_hash"),
            (time.monotonic() - started) * 1000,
            len(result.message_ids),
            result.message_id,
        )
    except DeliveryLeaseLost:
        logger.warning(
            "Notification ownership lost; delivery_id=%s test=%s",
            item["id"],
            item.get("is_test", False),
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - redact errors; unknown acceptance must stop replay
        error = (
            DeliveryPartError("terminal", type(exc).__name__)
            if isinstance(exc, PromoMessageValidationError)
            else classify_delivery_error(exc)
        )
        status = {
            "retryable": "failed",
            "terminal": "failed",
            "blocked": "blocked",
            "uncertain": "uncertain",
        }[error.kind]
        logger.warning(
            "Notification delivery result; delivery_id=%s campaign_id=%s test=%s status=%s code=%s",
            item["id"],
            item["campaign_id"],
            item.get("is_test", False),
            status,
            error.error_code,
        )
        try:
            await _finish(item, status=status, error=error)
        except DeliveryLeaseLost:
            logger.warning(
                "Notification failure result lost lease; delivery_id=%s", item["id"]
            )


async def _refresh_campaign(campaign_id: int) -> None:
    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'queued') AS queued,
                COUNT(*) FILTER (WHERE status = 'sending') AS sending,
                COUNT(*) FILTER (WHERE status = 'sent') AS sent,
                COUNT(*) FILTER (WHERE status = 'failed' AND attempts < ?) AS retryable_failed,
                COUNT(*) FILTER (WHERE (status = 'failed' AND attempts >= ?)
                                OR status = 'uncertain') AS terminal_failed,
                COUNT(*) FILTER (WHERE status = 'blocked') AS blocked,
                COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled
            FROM notification_deliveries WHERE campaign_id = ?
            """,
            (MAX_ATTEMPTS, MAX_ATTEMPTS, campaign_id),
        )
        row = await cursor.fetchone()
        if not row:
            return
        queued, sending, retryable_failed, terminal_failed, sent, blocked, cancelled = (
            int(row[key] or 0)
            for key in (
                "queued",
                "sending",
                "retryable_failed",
                "terminal_failed",
                "sent",
                "blocked",
                "cancelled",
            )
        )
        pending = queued + sending + retryable_failed
        await connection.execute(
            """
            UPDATE notification_campaigns
            SET queued_count = ?, sent_count = ?, failed_count = ?, blocked_count = ?, cancelled_count = ?,
                status = CASE WHEN status = 'cancelled' THEN status
                              WHEN ? = 0 THEN 'completed' ELSE status END,
                completed_at = CASE WHEN status <> 'cancelled' AND ? = 0
                    THEN COALESCE(completed_at, CURRENT_TIMESTAMP) ELSE completed_at END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                queued + retryable_failed,
                sent,
                terminal_failed,
                blocked,
                cancelled,
                pending,
                pending,
                campaign_id,
            ),
        )
        await connection.commit()


async def _refresh_item(item: dict[str, Any]) -> None:
    if item.get("is_test"):
        from bot.promo_campaigns import refresh_test_state

        await refresh_test_state(int(item["campaign_id"]), item.get("content_hash"))
    else:
        await _refresh_campaign(int(item["campaign_id"]))


async def notification_campaign_worker(bot: Bot) -> None:
    await ensure_internal_admin_notification_schema()
    await _recover_expired_leases()
    await _recover_expired_test_leases()
    logger.info("Notification campaign worker started")
    while True:
        item: dict[str, Any] | None = None
        try:
            await _cancel_obsolete_tests()
            item = await _claim_test_delivery() or await _claim_delivery()
            if item is None:
                await _recover_expired_leases()
                await _recover_expired_test_leases()
                await asyncio.sleep(POLL_SECONDS)
                continue
            await process_delivery(bot, item)
            await _refresh_item(item)
            await asyncio.sleep(BATCH_DELAY_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - redact errors; unknown acceptance must stop replay
            # Do not log raw provider exceptions, which may contain credentials.
            logger.error(
                "Notification worker iteration failed; code=%s", type(exc).__name__
            )
            if item is not None:
                try:
                    await _refresh_item(item)
                except Exception as refresh_error:  # noqa: BLE001 - keep worker alive without leaking provider data
                    logger.error(
                        "Notification refresh failed; code=%s",
                        type(refresh_error).__name__,
                    )
            await asyncio.sleep(POLL_SECONDS)


def ensure_notification_campaign_worker(bot: Bot) -> asyncio.Task[None]:
    global _WORKER_TASK
    if _WORKER_TASK is None or _WORKER_TASK.done():
        _WORKER_TASK = asyncio.create_task(
            notification_campaign_worker(bot), name="notification-campaign-worker"
        )
    return _WORKER_TASK
