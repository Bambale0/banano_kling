"""Authenticated two-sided account linking with atomic wallet preservation."""
from __future__ import annotations

import hmac
import secrets
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from bot import db as db_backend

from .actor import legacy_product_owner
from .commercial_store import (
    ensure_commercial_schema,
    lock_catalog,
    merge_commercial_terms,
)
from .errors import AuthenticationError, PreviewConflict
from .store import Account, _token_hash
from .wallet import Balance, WalletService, canonical_account, ensure_wallet_schema

LINK_SCHEMA = '''CREATE TABLE IF NOT EXISTS shared_account_links (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    source_account_id TEXT NOT NULL REFERENCES shared_accounts(id),
    source_platform TEXT NOT NULL,
    source_external_id BIGINT NOT NULL,
    target_platform TEXT NOT NULL,
    target_account_id TEXT REFERENCES shared_accounts(id),
    target_external_id BIGINT,
    policy_revision BIGINT NOT NULL,
    expires_at_epoch BIGINT NOT NULL,
    source_confirmed INTEGER NOT NULL DEFAULT 0 CHECK(source_confirmed IN (0, 1)),
    target_confirmed INTEGER NOT NULL DEFAULT 0 CHECK(target_confirmed IN (0, 1)),
    revision BIGINT NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending', 'awaiting_confirmation', 'committed', 'cancelled')),
    result_account_id TEXT REFERENCES shared_accounts(id),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)'''
COLUMNS = ('id', 'token_hash', 'source_account_id', 'source_platform', 'source_external_id', 'target_platform',
           'target_account_id', 'target_external_id', 'policy_revision', 'expires_at_epoch',
           'source_confirmed', 'target_confirmed', 'revision', 'state', 'result_account_id')


class LinkExpired(ValueError):
    """The pending consent invitation is no longer valid."""


def _party(link: dict, actor: Account) -> str | None:
    identity = actor.identity
    if identity.platform == link['source_platform'] and identity.external_id == link['source_external_id']:
        return 'source'
    if identity.platform == link['target_platform'] and identity.external_id == link['target_external_id']:
        return 'target'
    return None


def _payload(link: dict) -> dict:
    # Returned only to authenticated participants. Identity must be visible so
    # each person can verify the recipient before giving irreversible consent.
    return {key: link[key] for key in ('id', 'state', 'revision', 'expires_at_epoch', 'source_platform', 'target_platform')} | {
        'source_confirmed': bool(link['source_confirmed']), 'target_confirmed': bool(link['target_confirmed']),
        'account_id': link['result_account_id'],
        'source_identity': {'platform': link['source_platform'], 'external_id': str(link['source_external_id'])},
        'target_identity': None if link['target_external_id'] is None else {
            'platform': link['target_platform'], 'external_id': str(link['target_external_id'])},
    }


async def ensure_link_schema(db) -> None:
    await ensure_wallet_schema(db)
    await ensure_commercial_schema(db)
    if db_backend.is_postgres():
        await db.execute('SELECT pg_advisory_xact_lock(?)', (80420161107,))
    else:
        await db.execute('BEGIN IMMEDIATE')
    try:
        await getattr(db, 'execute_native_ddl', db.execute)(LINK_SCHEMA)
        await db.commit()
    except Exception:
        await db.rollback()
        raise


class LinkService:
    def __init__(self, policy):
        self.policy = policy

    @asynccontextmanager
    async def _transaction(self, link_id: str | None = None):
        async with db_backend.connect() as db:
            await ensure_link_schema(db)
            if not db_backend.is_postgres():
                await db.execute('BEGIN IMMEDIATE')
            try:
                link = None
                if link_id is not None:
                    suffix = ' FOR UPDATE' if db_backend.is_postgres() else ''
                    row = await (await db.execute('SELECT ' + ', '.join(COLUMNS) + ' FROM shared_account_links WHERE id = ?' + suffix,
                                                 (link_id,))).fetchone()
                    if not row:
                        raise AuthenticationError('Invitation unavailable')
                    link = {column: row[index] for index, column in enumerate(COLUMNS)}
                yield db, link
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    def _pending(self, link):
        if link['state'] == 'cancelled' or link['expires_at_epoch'] <= int(time.time()) or link['policy_revision'] != self.policy.revision:
            raise LinkExpired('Invitation expired or cancelled')

    async def accept_token(self, actor: Account, token: str) -> dict:
        digest = _token_hash(token)
        async with db_backend.connect() as db:
            await ensure_link_schema(db)
            row = await (await db.execute('SELECT id FROM shared_account_links WHERE token_hash = ?', (digest,))).fetchone()
        if not row:
            raise AuthenticationError('Invitation unavailable')
        return await self.operate(actor, row[0], 'accept', {'token': token})

    async def create(self, actor: Account, target_platform: str) -> dict:
        if target_platform not in {'telegram', 'vk'} or target_platform == actor.identity.platform:
            raise ValueError('Choose the other platform')
        token = secrets.token_urlsafe(32)
        link_id, expires = uuid4().hex, int(time.time()) + self.policy.link_ttl_seconds
        async with self._transaction() as (db, _):
            await db.execute('''INSERT INTO shared_account_links
                (id, token_hash, source_account_id, source_platform, source_external_id, target_platform, policy_revision, expires_at_epoch)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                             (link_id, _token_hash(token), actor.id, actor.identity.platform, actor.identity.external_id,
                              target_platform, self.policy.revision, expires))
        return {'id': link_id, 'token': token, 'expires_at_epoch': expires, 'state': 'pending', 'revision': 0}

    async def operate(self, actor: Account, link_id: str, action: str, body: dict) -> dict:
        async with self._transaction(link_id) as (db, link):
            party = _party(link, actor)
            if action == 'accept':
                if not hmac.compare_digest(_token_hash(body.get('token')), link['token_hash']):
                    raise AuthenticationError('Invitation unavailable')
                if actor.identity.platform != link['target_platform']:
                    raise PermissionError('Invitation requires the other platform')
                if link['target_external_id'] is not None and party != 'target':
                    raise PreviewConflict('Invitation already has a recipient')
            elif not party:
                raise PermissionError('Invitation does not belong to this identity')
            if link['state'] == 'committed':
                return _payload(link)
            self._pending(link)
            if action == 'accept':
                if link['target_external_id'] is None:
                    link.update(target_account_id=actor.id, target_external_id=actor.identity.external_id,
                                revision=link['revision'] + 1, state='awaiting_confirmation')
            elif action in {'confirm', 'cancel'}:
                already = action == 'confirm' and bool(link[party + '_confirmed'])
                if not already:
                    expected = body.get('expected_revision')
                    if type(expected) is not int or expected < 0:
                        raise ValueError('Invalid expected revision')
                    if expected != link['revision']:
                        raise PreviewConflict('Invitation changed; reload before confirming')
                    if action == 'cancel':
                        if party != 'source':
                            raise PermissionError('Only the sender can cancel')
                        link['state'] = 'cancelled'
                    else:
                        if link['target_external_id'] is None:
                            raise PreviewConflict('Recipient has not authenticated')
                        link[party + '_confirmed'] = 1
                    link['revision'] += 1
            elif action != 'get':
                raise ValueError('Unknown link action')
            if link['source_confirmed'] and link['target_confirmed']:
                link['result_account_id'] = await self._merge(db, link)
                link['state'] = 'committed'
            if action != 'get':
                await db.execute('''UPDATE shared_account_links SET target_account_id = ?, target_external_id = ?,
                    source_confirmed = ?, target_confirmed = ?, revision = ?, state = ?, result_account_id = ? WHERE id = ?''',
                                 (link['target_account_id'], link['target_external_id'], link['source_confirmed'], link['target_confirmed'],
                                  link['revision'], link['state'], link['result_account_id'], link_id))
            return _payload(link)

    async def _merge(self, db, link: dict) -> str:
        # Global lock order: link, catalog, sorted accounts. Commercial edits
        # take catalog before account too, preventing merge/edit deadlocks.
        await lock_catalog(db)
        originals = [link['source_account_id'], link['target_account_id']]
        accounts = sorted({await canonical_account(db, account_id) for account_id in originals})
        suffix = ' FOR UPDATE' if db_backend.is_postgres() else ''
        for account_id in accounts:
            row = await (await db.execute('SELECT status FROM shared_accounts WHERE id = ?' + suffix, (account_id,))).fetchone()
            if not row or row[0] != 'active':
                raise PreviewConflict('Accounts changed; create a new invitation')
        canonical = accounts[0]
        # Proofs refer to identities, not arbitrary accounts submitted by the client.
        for platform, external, original in [(link['source_platform'], link['source_external_id'], originals[0]),
                                              (link['target_platform'], link['target_external_id'], originals[1])]:
            row = await (await db.execute('SELECT account_id FROM shared_account_identities WHERE platform = ? AND external_id = ?',
                                         (platform, external))).fetchone()
            if not row or row[0] != await canonical_account(db, original):
                raise PreviewConflict('Identity ownership changed')
        # Check product provenance before any commercial, wallet or identity mutation.
        # Existing Telegram legacy links are the sole product-owner mapping.
        try:
            owners = {owner[0] for account_id in accounts
                      if (owner := await legacy_product_owner(db, account_id)) is not None}
        except AuthenticationError as exc:
            raise PreviewConflict('Product ownership requires reconciliation') from exc
        if len(owners) > 1:
            raise PreviewConflict('Different product owners require reconciliation')
        if len(accounts) == 1:
            return canonical
        other = accounts[1]
        conflict = await (await db.execute('''SELECT platform FROM shared_account_identities WHERE account_id IN (?, ?)
            GROUP BY platform HAVING COUNT(*) > 1''', (canonical, other))).fetchone()
        if conflict:
            raise PreviewConflict('An account already has a different identity on this platform')
        await merge_commercial_terms(db, canonical, other, link['id'])
        for scope in ('sandbox', 'live'):
            service = WalletService(scope)
            balances = {}
            for account_id in accounts:
                await db.execute('INSERT INTO shared_wallets(scope, account_id) VALUES (?, ?) ON CONFLICT(scope, account_id) DO NOTHING', (scope, account_id))
                row = await (await db.execute('SELECT available_units, reserved_units, revision FROM shared_wallets WHERE scope = ? AND account_id = ?', (scope, account_id))).fetchone()
                balances[account_id] = Balance(int(row[0]), int(row[1]), int(row[2]))
            incoming = balances[other]
            total = incoming.available_units + incoming.reserved_units
            if total:
                await service._append(db, other, incoming, f'link:{link["id"]}:{scope}:out', 'transfer_out', total, link['id'],
                                      -incoming.available_units, -incoming.reserved_units)
                await service._append(db, canonical, balances[canonical], f'link:{link["id"]}:{scope}:in', 'transfer_in', total, link['id'],
                                      incoming.available_units, incoming.reserved_units)
            await db.execute('UPDATE shared_wallet_reservations SET account_id = ? WHERE scope = ? AND account_id = ?', (canonical, scope, other))
        await db.execute('UPDATE shared_account_identities SET account_id = ? WHERE account_id = ?', (canonical, other))
        await db.execute('UPDATE shared_account_legacy_links SET account_id = ? WHERE account_id = ?', (canonical, other))
        await db.execute("UPDATE shared_accounts SET status = 'merged', merged_into = ? WHERE id = ?", (canonical, other))
        return canonical
