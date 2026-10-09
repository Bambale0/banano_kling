"""Transactional referral receipts; Telegram I/O never runs in a billing transaction.

Reuse the campaign sender's frozen payload/progress contract without manufacturing
campaigns. Ambiguous API outcomes require reconciliation, never automatic replay.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import time
from uuid import uuid4

from bot import db as db_backend
from bot.promo_message import (
    REQUEST_TIMEOUT_SECONDS,
    DeliveryLeaseLost,
    build_message_snapshot,
    classify_delivery_error,
    deliver_message_snapshot,
)

logger = logging.getLogger(__name__)
POLL_SECONDS = 1.0
LEASE_SECONDS = 90
MAX_ATTEMPTS = 5
_WORKER_TASK: asyncio.Task | None = None
assert REQUEST_TIMEOUT_SECONDS < LEASE_SECONDS

class ReferralProgressStorageError(Exception):
    """Let lease recovery inspect durable progress after a storage failure."""


SCHEMA = """CREATE TABLE IF NOT EXISTS referral_notification_outbox (
    event_key TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('attached', 'bonus')),
    referred_id BIGINT NOT NULL REFERENCES users(id),
    referrer_id BIGINT NOT NULL REFERENCES users(id),
    telegram_id BIGINT NOT NULL,
    snapshot TEXT NOT NULL,
    delivery_parts TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'sending', 'failed', 'sent', 'blocked', 'terminal', 'uncertain')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    lease_until DOUBLE PRECISION,
    attempt_token TEXT,
    last_error TEXT,
    telegram_message_id BIGINT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP,
    UNIQUE(kind, referred_id)
)"""


async def init_referral_notification_schema(db) -> None:
    ddl = getattr(db, 'execute_native_ddl', db.execute)
    await ddl(SCHEMA)
    await ddl("""CREATE INDEX IF NOT EXISTS idx_referral_notification_pending
                 ON referral_notification_outbox(status, next_attempt_at)""")


async def enqueue_referral_notification(db, kind: str, referrer_id: int,
                                        referred_id: int, bonus: float) -> None:
    """Insert only alongside a new attachment/grant, using the caller's transaction."""
    if kind not in {'attached', 'bonus'}:
        raise ValueError('Unknown referral notification kind')
    cursor = await db.execute(
        """SELECT inviter.telegram_id, invited.username, invited.first_name, invited.last_name
           FROM users inviter JOIN users invited ON invited.id = ? WHERE inviter.id = ?""",
        (referred_id, referrer_id),
    )
    row = await cursor.fetchone()
    if not row:
        raise RuntimeError('Referral notification recipient missing')
    name = html.escape(' '.join(str(row[key] or '').strip()[:128]
                               for key in ('first_name', 'last_name')).strip() or 'Новый пользователь')
    username = str(row['username'] or '').strip().lstrip('@')[:64]
    identity = f'<b>{name}</b>' + (f'\n@{html.escape(username)}' if username else '')
    amount = f'{float(bonus):g}'
    if kind == 'attached':
        text = ('🎉 <b>Новый реферал</b>\n\n'
                f'К вам присоединился: {identity}\n\n'
                f'Бонус <code>{amount}</code>🍌 будет начислен после первой '
                'генерации реферала, принятой сервисом в работу. '
                'Партнёрские начисления с оплат появятся в вашей статистике.')
    else:
        text = ('🍌 <b>Начислен бонус за реферала</b>\n\n'
                f'{identity}\n\nПервая генерация реферала принята сервисом в работу. '
                f'Вам начислено <code>{amount}</code>🍌.')
    snapshot = build_message_snapshot({'schema_version': 2, 'text': text, 'parse_mode': 'HTML'}, None)
    await db.execute(
        """INSERT INTO referral_notification_outbox
           (event_key, kind, referred_id, referrer_id, telegram_id, snapshot)
           VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(event_key) DO NOTHING""",
        (f'{kind}:{referred_id}', kind, referred_id, referrer_id, row['telegram_id'],
         json.dumps(snapshot, ensure_ascii=False)),
    )


async def recover_expired_referral_notifications() -> int:
    """Recover known progress only; a saved API intent without receipt is uncertain."""
    recovered = 0
    now = time.time()
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        rows = await (await db.execute(
            """SELECT event_key, attempt_token, delivery_parts, attempts, snapshot, telegram_id
               FROM referral_notification_outbox WHERE status = 'sending' AND lease_until < ?""",
            (now,),
        )).fetchall()
        for row in rows:
            message_id = None
            retry_after = 0
            try:
                parts = json.loads(row['delivery_parts'])
                if not isinstance(parts, list):
                    raise TypeError('Invalid progress')
                if parts and all(p.get('status') == 'sent' and p.get('message_ids') for p in parts):
                    async def refuse_new_progress(_parts):
                        raise DeliveryLeaseLost('Recovery cannot make an API attempt')
                    # Shared validation checks count, hashes and positive receipts.
                    # All-sent progress returns without API or persistence calls.
                    result = await deliver_message_snapshot(
                        None, int(row['telegram_id']), json.loads(row['snapshot']),
                        delivery_parts=parts, save_progress=refuse_new_progress,
                    )
                    status = 'sent'
                    message_id = result.message_id
                elif all(p.get('status') in {'pending', 'retryable', 'sent'} for p in parts):
                    status = 'failed'
                    retry_after = max([int(p.get('retry_after') or 0) for p in parts] or [0])
                else:
                    status = 'uncertain'
            except Exception:  # noqa: BLE001 - malformed saved progress must fail closed
                status = 'uncertain'
                parts = None
            cursor = await db.execute(
                """UPDATE referral_notification_outbox SET status = ?,
                   attempts = ?, lease_until = NULL, attempt_token = NULL,
                   telegram_message_id = ?, next_attempt_at = ?,
                   sent_at = CASE WHEN ? = 'sent' THEN CURRENT_TIMESTAMP ELSE sent_at END,
                   last_error = ? WHERE event_key = ? AND status = 'sending'
                   AND attempt_token = ? AND lease_until < ?""",
                (status, max(0, row['attempts'] - 1) if parts == [] else row['attempts'],
                 message_id, now + retry_after, status,
                 None if status == 'sent' else 'expired_lease_' + status,
                 row['event_key'], row['attempt_token'], now),
            )
            recovered += max(0, cursor.rowcount)
        await db.commit()
    return recovered


async def _claim() -> dict | None:
    now = time.time()
    token = uuid4().hex
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        # One conditional claim wins on both SQLite and PostgreSQL. Credit waits
        # for its attachment receipt (if any) to reach a terminal delivery state.
        cursor = await db.execute(
            """SELECT o.* FROM referral_notification_outbox o
               WHERE o.status IN ('queued', 'failed') AND o.next_attempt_at <= ?
                 AND o.attempts < ? AND NOT EXISTS (
                   SELECT 1 FROM referral_notification_outbox first_event
                   WHERE o.kind = 'bonus' AND first_event.referred_id = o.referred_id
                     AND first_event.kind = 'attached'
                     AND first_event.status IN ('queued', 'sending', 'failed')
                     AND (first_event.status = 'sending' OR first_event.attempts < ?))
               ORDER BY o.created_at, CASE WHEN o.kind = 'attached' THEN 0 ELSE 1 END,
                        o.event_key LIMIT 1""",
            (now, MAX_ATTEMPTS, MAX_ATTEMPTS),
        )
        row = await cursor.fetchone()
        if not row:
            await db.commit()
            return None
        claimed = await db.execute(
            """UPDATE referral_notification_outbox SET status = 'sending', attempts = attempts + 1,
               attempt_token = ?, lease_until = ?, last_error = NULL
               WHERE event_key = ? AND status IN ('queued', 'failed') AND next_attempt_at <= ?
                 AND attempts < ?""",
            (token, now + LEASE_SECONDS, row['event_key'], now, MAX_ATTEMPTS),
        )
        await db.commit()
        if claimed.rowcount != 1:
            return None
        return {**dict(row), 'attempt_token': token, 'attempts': row['attempts'] + 1}


async def _save_progress(item: dict, parts: list[dict]) -> None:
    now = time.time()
    async with db_backend.connect() as db:
        saved = await db.execute(
            """UPDATE referral_notification_outbox SET delivery_parts = ?, lease_until = ?
               WHERE event_key = ? AND status = 'sending' AND attempt_token = ? AND lease_until > ?""",
            (json.dumps(parts), now + LEASE_SECONDS, item['event_key'], item['attempt_token'], now),
        )
        await db.commit()
        if saved.rowcount != 1:
            raise DeliveryLeaseLost('Referral receipt lease lost')


async def _finish(item: dict, status: str, *, message_id=None, error=None) -> None:
    now = time.time()
    delay = (error.retry_after or 0) if error else 0
    async with db_backend.connect() as db:
        updated = await db.execute(
            """UPDATE referral_notification_outbox SET status = ?, telegram_message_id = ?,
               sent_at = CASE WHEN ? = 'sent' THEN CURRENT_TIMESTAMP ELSE sent_at END,
               last_error = ?, next_attempt_at = ?, attempt_token = NULL, lease_until = NULL
               WHERE event_key = ? AND status = 'sending' AND attempt_token = ? AND lease_until > ?""",
            (status, message_id, status, error.error_code if error else None, now + delay,
             item['event_key'], item['attempt_token'], now),
        )
        await db.commit()
        if updated.rowcount != 1:
            raise DeliveryLeaseLost('Referral completion lease lost')
    logger.info('Referral notification %s: event_key=%s', status, item['event_key'])


async def deliver_pending_referral_notification(bot) -> bool:
    item = await _claim()
    if item is None:
        return False
    try:
        async def save_progress(parts):
            try:
                await _save_progress(item, parts)
            except DeliveryLeaseLost:
                raise
            except Exception as exc:  # Distinguish storage from API outcomes.
                raise ReferralProgressStorageError("Referral progress persistence failed") from exc
        result = await deliver_message_snapshot(
            bot, int(item['telegram_id']), json.loads(item['snapshot']),
            delivery_parts=json.loads(item['delivery_parts']), save_progress=save_progress,
        )
    except DeliveryLeaseLost:
        logger.warning('Referral notification lease lost: event_key=%s', item['event_key'])
    except (asyncio.CancelledError, ReferralProgressStorageError):
        raise
    except Exception as exc:  # noqa: BLE001 - delivery boundary classifies safe retry vs uncertainty
        error = classify_delivery_error(exc)
        status = 'failed' if error.kind == 'retryable' and item['attempts'] < MAX_ATTEMPTS else error.kind
        if status == 'retryable':
            status = 'terminal'
        try:
            await _finish(item, status, error=error)
        except DeliveryLeaseLost:
            logger.warning('Referral notification failure lease lost: event_key=%s', item['event_key'])
    else:
        # If finalization fails after a saved receipt, leave the claim for
        # recovery rather than misclassifying an already-confirmed send.
        await _finish(item, 'sent', message_id=result.message_id)
    return True


async def referral_notification_worker(bot) -> None:
    logger.info('Referral notification worker started')
    while True:
        try:
            await recover_expired_referral_notifications()
            delivered = await deliver_pending_referral_notification(bot)
            await asyncio.sleep(0.05 if delivered else POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - resilient worker, log types only
            logger.error('Referral notification worker failed: error_type=%s', type(exc).__name__)
            await asyncio.sleep(POLL_SECONDS)


def ensure_referral_notification_worker(bot) -> asyncio.Task:
    global _WORKER_TASK
    if _WORKER_TASK is None or _WORKER_TASK.done():
        _WORKER_TASK = asyncio.create_task(referral_notification_worker(bot), name='referral-notifications')
    return _WORKER_TASK


async def stop_referral_notification_worker() -> None:
    global _WORKER_TASK
    if _WORKER_TASK is not None:
        _WORKER_TASK.cancel()
        try:
            await _WORKER_TASK
        except asyncio.CancelledError:
            pass
        _WORKER_TASK = None
