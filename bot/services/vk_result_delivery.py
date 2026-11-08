"""Durable VK transport jobs, independent from generation charges/refunds."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
from contextlib import asynccontextmanager

from bot import db as db_backend
from bot.shared_accounts.auth import VerifiedIdentity
from bot.shared_accounts.policy import load_policy
from bot.shared_accounts.schema import ensure_schema
from bot.shared_accounts.wallet import canonical_account

from .vk_result_transport import (
    VKBeforeSendUnavailable,
    VKConfigurationRequired,
    VKRejected,
    VKSendUncertain,
)

logger = logging.getLogger(__name__)
SCHEMA = '''CREATE TABLE IF NOT EXISTS vk_result_deliveries (
    task_id BIGINT PRIMARY KEY REFERENCES generation_tasks(id),
    external_task_id TEXT NOT NULL,
    account_id TEXT NOT NULL REFERENCES shared_accounts(id),
    vk_user_id BIGINT NOT NULL CHECK(vk_user_id > 0),
    community_id BIGINT NOT NULL CHECK(community_id > 0),
    random_id BIGINT NOT NULL UNIQUE CHECK(random_id < 0 AND random_id > -2147483648),
    result_url TEXT NOT NULL, message TEXT NOT NULL,
    attachment TEXT, prepared INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN
      ('pending','preparing','sending','delivered','permission_required','uncertain','failed','access_revoked','configuration_required')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_epoch BIGINT NOT NULL DEFAULT 0,
    lease_token TEXT, lease_until_epoch BIGINT NOT NULL DEFAULT 0,
    receipt_id BIGINT, reason TEXT,
    created_at_epoch BIGINT NOT NULL, updated_at_epoch BIGINT NOT NULL)'''


class VKDeliveryQueue:
    def __init__(self, sender, *, clock=time.time):
        self.sender, self.clock = sender, clock
        self._reconcile_after = 0

    @asynccontextmanager
    async def transaction(self):
        async with db_backend.connect() as db:
            await ensure_schema(db)
            await db.execute('SELECT pg_advisory_xact_lock(?)' if db_backend.is_postgres() else 'BEGIN IMMEDIATE',
                             (80420161112,) if db_backend.is_postgres() else ())
            try:
                await getattr(db, 'execute_native_ddl', db.execute)(SCHEMA)
                await db.commit()
                if not db_backend.is_postgres():
                    await db.execute('BEGIN IMMEDIATE')
                db.row_factory = db_backend.Row
                yield db
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def enqueue(self, lookup_id: str) -> bool:
        from bot.database import get_task_by_id

        task = await get_task_by_id(lookup_id)
        policy = await load_policy()
        async with self.transaction() as db:
            if not task or task.status != 'completed' or task.type not in {'image', 'video'} or not task.result_url:
                return False
            try:
                metadata = json.loads(task.request_data or '{}')
            except (TypeError, ValueError):
                return False
            vk_user = metadata.get('origin_vk_user_id') if isinstance(metadata, dict) else None
            account = metadata.get('origin_account_id') if isinstance(metadata, dict) else None
            if (not isinstance(metadata, dict) or metadata.get('origin_platform') != 'vk'
                    or metadata.get('vk_chat_delivery_requested') is not True
                    or type(vk_user) is not int or vk_user <= 0
                    or not isinstance(account, str) or not re.fullmatch('[0-9a-f]{32}', account)):
                return False
            if not policy.vk_result_delivery_enabled or not policy.vk_community_id or not policy.allows(VerifiedIdentity('vk', vk_user)):
                return False
            try:
                canonical = await canonical_account(db, account)
            except (ValueError, PermissionError):
                return False
            suffix = ' FOR UPDATE' if db_backend.is_postgres() else ''
            owner = await (await db.execute('SELECT status FROM shared_accounts WHERE id = ?' + suffix, (canonical,))).fetchone()
            if not owner or owner[0] != 'active':
                return False
            valid = await (await db.execute('''SELECT identity.account_id FROM shared_account_identities identity
                JOIN shared_account_legacy_links legacy ON legacy.account_id = identity.account_id
                WHERE identity.platform = 'vk' AND identity.external_id = ? AND identity.account_id = ?
                  AND legacy.source = 'telegram' AND legacy.legacy_user_id = ?''', (vk_user, canonical, task.user_id))).fetchone()
            if not valid:
                return False
            now = int(self.clock())
            for _ in range(8):
                inserted = await db.execute('''INSERT INTO vk_result_deliveries
                    (task_id,external_task_id,account_id,vk_user_id,community_id,random_id,result_url,message,created_at_epoch,updated_at_epoch)
                    VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING''',
                    (task.id, task.task_id, account, vk_user, policy.vk_community_id,
                     # The native sender uses positive timestamps. Keep these
                     # signed VK protocol IDs separate from that sender.
                     -(secrets.randbelow(2**31 - 1) + 1), task.result_url,
                     policy.vk_result_message_template.format(result_url=task.result_url, task_id=task.task_id), now, now))
                saved = await (await db.execute('SELECT vk_user_id,result_url FROM vk_result_deliveries WHERE task_id = ?', (task.id,))).fetchone()
                if saved:
                    if inserted.rowcount == 1:
                        logger.info('vk_delivery_accepted task_id=%s account_id=%s community_id=%s', task.id, account, policy.vk_community_id)
                    return saved[0] == vk_user and saved[1] == task.result_url
            return False

    async def reconcile(self) -> None:
        policy = await load_policy()
        if not policy.enabled or not policy.vk_result_delivery_enabled:
            return
        platform = "request_data::jsonb ->> 'origin_platform'" if db_backend.is_postgres() else "json_extract(request_data, '$.origin_platform')"
        recipient = "request_data::jsonb ->> 'origin_vk_user_id'" if db_backend.is_postgres() else "json_extract(request_data, '$.origin_vk_user_id')"
        async with self.transaction() as db:
            rows = await (await db.execute(f'''SELECT g.id, g.task_id FROM generation_tasks g
                LEFT JOIN vk_result_deliveries d ON d.task_id = g.id WHERE d.task_id IS NULL
                AND g.id > ?
                AND g.status = 'completed' AND g.type IN ('image', 'video') AND COALESCE(g.result_url, '') <> ''
                AND CASE WHEN json_valid(g.request_data) THEN {platform} ELSE NULL END = 'vk'
                AND CASE WHEN json_valid(g.request_data) THEN {recipient} ELSE NULL END IS NOT NULL
                ORDER BY g.id LIMIT 50''', (self._reconcile_after,))).fetchall()
        # Ineligible old rows must not monopolize every recovery sweep. Wrap so
        # later ownership/policy corrections also become eligible again.
        self._reconcile_after = rows[-1][0] if len(rows) == 50 else 0
        for row in rows:
            await self.enqueue(row[1])

    async def claim(self, policy) -> dict | None:
        now, token = int(self.clock()), secrets.token_hex(16)
        async with self.transaction() as db:
            await db.execute("UPDATE vk_result_deliveries SET state = 'uncertain', reason = 'send_ack_unknown', updated_at_epoch = ? WHERE state = 'sending' AND lease_until_epoch <= ?", (now, now))
            await db.execute("UPDATE vk_result_deliveries SET state = 'failed', reason = 'retry_budget_exhausted', updated_at_epoch = ? WHERE state IN ('pending','preparing') AND lease_until_epoch <= ? AND attempts >= ?", (now, now, policy.vk_delivery_max_attempts))
            suffix = ' FOR UPDATE SKIP LOCKED' if db_backend.is_postgres() else ''
            row = await (await db.execute('''SELECT d.*, g.type AS result_type
                FROM vk_result_deliveries d
                JOIN generation_tasks g ON g.id = d.task_id
                WHERE d.state IN ('pending','preparing')
                AND d.next_attempt_epoch <= ? AND d.lease_until_epoch <= ?
                AND d.attempts < ? ORDER BY d.task_id LIMIT 1''' + suffix,
                (now, now, policy.vk_delivery_max_attempts))).fetchone()
            if not row:
                return None
            changed = await db.execute('''UPDATE vk_result_deliveries SET state = 'preparing', attempts = attempts + 1,
                lease_token = ?, lease_until_epoch = ?, updated_at_epoch = ?
                WHERE task_id = ? AND state IN ('pending','preparing') AND lease_until_epoch <= ?''',
                (token, now + 300, now, row['task_id'], now))
            if changed.rowcount != 1:
                return None
            return {**dict(row), 'lease_token': token, 'attempts': row['attempts'] + 1}

    async def finish(self, job, state: str, *, reason=None, receipt=None, delay=0):
        now = int(self.clock())
        async with self.transaction() as db:
            changed = await db.execute('''UPDATE vk_result_deliveries SET state = ?, reason = ?, receipt_id = ?,
                next_attempt_epoch = ?, lease_until_epoch = 0, updated_at_epoch = ?
                WHERE task_id = ? AND lease_token = ? AND (state IN ('preparing','sending')
                  OR (? = 'delivered' AND state = 'uncertain' AND reason = 'send_ack_unknown'))''',
                (state, reason, receipt, now + delay, now, job['task_id'], job['lease_token'],
                 'delivered' if state == 'delivered' and type(receipt) is int and receipt > 0 else ''))
        if changed.rowcount == 1:
            logger.info('vk_result_delivery task_id=%s state=%s reason=%s attempts=%s', job['task_id'], state, reason, job['attempts'])

    async def begin_send(self, job, attachment):
        now = int(self.clock())
        async with self.transaction() as db:
            changed = await db.execute('''UPDATE vk_result_deliveries SET state = 'sending', attachment = ?,
                prepared = 1, updated_at_epoch = ? WHERE task_id = ? AND lease_token = ?
                AND state = 'preparing' AND lease_until_epoch > ?''',
                (attachment, now, job['task_id'], job['lease_token'], now))
            return changed.rowcount == 1

    async def tick(self):
        policy = await load_policy()
        if not policy.enabled or not policy.vk_result_delivery_enabled:
            return
        job = await self.claim(policy)
        if not job:
            return
        send_started = False
        try:
            if policy.vk_community_id != job['community_id']:
                await self.finish(job, 'configuration_required', reason='community_changed')
                return
            if not policy.allows(VerifiedIdentity('vk', job['vk_user_id'])):
                await self.finish(job, 'access_revoked', reason='preview_access_revoked')
                return
            if not await self.authorized(job):
                await self.finish(job, 'access_revoked', reason='result_owner_changed')
                return
            if not await self.sender.permission(job):
                await self.finish(job, 'permission_required', reason='messages_not_allowed')
                return
            attachment = job['attachment'] if job['prepared'] else await self.sender.prepare(job)
            # Recheck the kill switch and administrator ceiling after media I/O.
            latest = await load_policy()
            if (not latest.vk_result_delivery_enabled or latest.vk_community_id != job['community_id']
                    or not latest.allows(VerifiedIdentity('vk', job['vk_user_id']))):
                await self.finish(job, 'access_revoked', reason='delivery_policy_changed')
                return
            if not await self.authorized(job):
                await self.finish(job, 'access_revoked', reason='result_owner_changed')
                return
            if not await self.begin_send(job, attachment):
                return
            job['attachment'] = attachment
            send_started = True
            receipt = await self.sender.send(job)
            if type(receipt) is not int or receipt <= 0:
                raise VKSendUncertain()
            await self.finish(job, 'delivered', receipt=receipt)
        except VKConfigurationRequired:
            await self.finish(job, 'configuration_required', reason='sender_not_configured')
        except VKBeforeSendUnavailable:
            await self.finish(job, 'pending' if job['attempts'] < policy.vk_delivery_max_attempts else 'failed',
                              reason='pre_send_unavailable', delay=policy.vk_delivery_retry_seconds)
        except VKRejected as exc:
            if exc.code == 901:
                await self.finish(job, 'permission_required', reason='messages_not_allowed')
            elif exc.code == 6 and job['attempts'] < policy.vk_delivery_max_attempts:
                await self.finish(job, 'pending', reason='vk_rate_limit', delay=policy.vk_delivery_retry_seconds)
            else:
                await self.finish(job, 'failed', reason=f'vk_rejected_{exc.code}')
        except VKSendUncertain:
            await self.finish(job, 'uncertain', reason='send_ack_unknown')
        except Exception as exc:  # noqa: BLE001 - persist the phase before a worker boundary failure.
            # Unknown failures after send may hide a real receipt. Never resend.
            logger.error('vk_result_delivery_failed task_id=%s error_type=%s', job['task_id'], type(exc).__name__)
            await self.finish(job, 'uncertain' if send_started else 'failed', reason='operation_unconfirmed')

    async def authorized(self, job) -> bool:
        async with self.transaction() as db:
            try:
                canonical = await canonical_account(db, job['account_id'])
            except (ValueError, PermissionError):
                return False
            suffix = ' FOR UPDATE' if db_backend.is_postgres() else ''
            active = await (await db.execute('SELECT status FROM shared_accounts WHERE id = ?' + suffix, (canonical,))).fetchone()
            if not active or active[0] != 'active':
                return False
            row = await (await db.execute('''SELECT g.id FROM generation_tasks g
                JOIN shared_account_legacy_links legacy ON legacy.legacy_user_id = g.user_id AND legacy.source = 'telegram'
                JOIN shared_account_identities identity ON identity.account_id = legacy.account_id AND identity.platform = 'vk'
                WHERE g.id = ? AND g.status = 'completed' AND g.result_url = ?
                  AND identity.external_id = ? AND identity.account_id = ?''',
                (job['task_id'], job['result_url'], job['vk_user_id'], canonical))).fetchone()
            return row is not None


async def enqueue_vk_result(task_id: str):
    from .vk_result_transport import VKResultTransport

    return await VKDeliveryQueue(VKResultTransport()).enqueue(task_id)


def setup_vk_result_delivery(app):
    async def lifecycle(_app):
        from .vk_result_transport import VKResultTransport

        queue = VKDeliveryQueue(VKResultTransport())

        async def worker():
            while True:
                try:
                    await queue.reconcile()
                    await queue.tick()
                except Exception as exc:  # noqa: BLE001 - keep reconciliation alive; redact all remote errors.
                    logger.error('vk_delivery_worker_failed error_type=%s', type(exc).__name__)
                await asyncio.sleep(5)

        task = asyncio.create_task(worker(), name='vk-result-delivery')
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app.cleanup_ctx.append(lifecycle)
