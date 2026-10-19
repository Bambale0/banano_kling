"""Native Telegram launch receipts using the shared atomic repeat ledger.

`tg:` IDs are internal receipts, not editable Mini App drafts. Money and the
receipt's debit/refund are committed together by smart_repeat_store.repeat_finance.
"""
from __future__ import annotations

import asyncio
import json
import math
from contextlib import asynccontextmanager

from bot import db as db_backend
from bot import smart_repeat_store as store
from bot.smart_repeat_contract import AUTHORIZED_REPEAT, fail, source_fingerprint

PREFIX = 'tg:'


async def recover_unsubmitted(user, source_id: int) -> float:
    """Fence and refund only receipts which provably never reached task creation.

    record_accepted takes the same user lock and rejects a fenced native receipt
    before task creation/provider access, so even a suspended old worker cannot
    resume and submit after this refund. Bound/accepted tasks are never guessed
    failed or refunded here; their existing task recovery/watchdog owns them.
    """
    total = 0.0
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        await store._lock_user(db, user.id)
        rows = await (await db.execute(
            "SELECT * FROM smart_repeat_drafts WHERE user_id = ? AND source_id = ? "
            "AND id LIKE 'tg:%' AND status IN ('launching', 'unknown') "
            'AND task_id IS NULL AND accepted_task_json IS NULL AND provider_accepted = 0',
            (user.id, source_id),
        )).fetchall()
        for row in rows:
            amount = float(row['charge_amount']) - float(row['refund_amount'])
            if not math.isfinite(amount) or amount < 0:
                fail('OPERATION_CONFLICT', 'Не удалось подтвердить баланс операции.')
            changed = await db.execute(
                "UPDATE smart_repeat_drafts SET status = 'rejected', refund_amount = charge_amount, "
                'updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ? '
                "AND status IN ('launching', 'unknown') AND task_id IS NULL "
                'AND accepted_task_json IS NULL AND provider_accepted = 0', (row['id'], user.id),
            )
            if changed.rowcount == 1:
                total += amount
        if total:
            await db.execute('UPDATE users SET credits = credits + ?, updated_at = CURRENT_TIMESTAMP '
                             'WHERE id = ? AND telegram_id = ?', (total, user.id, user.telegram_id))
        await db.commit()
    if rows:
        store.event('native_unsubmitted_recovered', user_id=user.id, source_id=source_id,
                    receipts=len(rows), refund_amount=total)
    return total


@asynccontextmanager
async def authorized_launch(user, contract: dict, data: dict, quote_id: str, cost: float):
    source = contract['source']
    template = contract.get('template')
    version = int(template['version']) if template else 0
    receipt_id = PREFIX + quote_id
    source_hash = source_fingerprint(source)
    snapshot = {'native_telegram': True, 'source_id': source['id'], 'source_hash': source_hash,
                'template_version': version, 'model': data['img_service'], 'type': 'image',
                'body': {'reference_images': list(data.get('reference_images') or [])},
                'quote_signature': data.get('repeat_quote_signature')}
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        await store._lock_user(db, user.id)
        current = await store._current_source(db, source['id'], owner_id=user.id)
        if source_fingerprint(current) != source_hash:
            fail('TEMPLATE_CHANGED', 'Публикация изменилась. Откройте повтор заново.')
        latest = await (await db.execute('SELECT version FROM smart_repeat_templates '
            'WHERE source_id = ? ORDER BY version DESC LIMIT 1', (source['id'],))).fetchone()
        if (int(latest[0]) if latest else 0) != version:
            fail('TEMPLATE_CHANGED', 'Автор обновил поля. Откройте повтор заново.')
        changed = await db.execute(
            'INSERT INTO smart_repeat_drafts '
            '(id, user_id, telegram_id, source_id, template_version, status, state_json, quote_json, snapshot_json) '
            "VALUES (?, ?, ?, ?, ?, 'launching', ?, ?, ?) ON CONFLICT(id) DO NOTHING",
            (receipt_id, user.id, user.telegram_id, source['id'], version,
             json.dumps({'native_telegram': True}), json.dumps({'cost': cost, 'quote_id': quote_id}),
             json.dumps(snapshot)),
        )
        if changed.rowcount != 1:
            fail('OPERATION_ALREADY_CREATED', 'Этот повтор уже сохранён. Проверьте историю.')
        await db.commit()
    context = {'native_telegram': True, 'user_id': user.id, 'telegram_id': user.telegram_id,
               'request_task': asyncio.current_task(), 'draft_id': receipt_id, 'source_id': source['id'],
               'source_hash': source_hash, 'template_version': version,
               'owned_inputs': set(), 'overrides': {}}
    token = AUTHORIZED_REPEAT.set(context)
    try:
        yield receipt_id
    finally:
        AUTHORIZED_REPEAT.reset(token)
        # A hard kill can skip this write; the already committed launching row
        # and atomic financial ledger are sufficient for fenced recovery.
        try:
            async with db_backend.connect() as db:
                await db.execute(
                    "UPDATE smart_repeat_drafts SET status = CASE WHEN task_id IS NOT NULL THEN 'launched' "
                    "ELSE 'unknown' END, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ? "
                    "AND status = 'launching'", (receipt_id, user.id),
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001 - preserve the original error after a durable claim
            # The durable launching row already exists; do not mask cancellation
            # or a provider error with a best-effort status update failure.
            store.logger.warning('native_receipt_finalize_failed error_type=%s', type(exc).__name__)



async def replay_message(telegram_id: int, quote_id: str) -> str | None:
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        row = await (await db.execute(
            'SELECT status, task_id FROM smart_repeat_drafts WHERE id = ? AND telegram_id = ?',
            (PREFIX + quote_id, telegram_id),
        )).fetchone()
    if not row:
        return None
    if row['task_id']:
        return 'Повтор уже создан. Результат и статус доступны в истории.'
    if row['status'] == 'rejected':
        return 'Предыдущая попытка отменена без списания. Откройте новый повтор.'
    return 'Операция сохранена. Откройте повтор заново для проверки, без повторного списания.'
