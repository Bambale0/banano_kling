"""Audited administrator changes; preview configuration never alters live prices."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from uuid import uuid4

from bot import db as db_backend

from .commercial import (
    Catalog,
    CommercialValidation,
    Terms,
    exact,
    key,
    payment_methods,
    units,
)
from .errors import PreviewConflict
from .schema import ensure_schema
from .wallet import canonical_account

CATALOG_KEY = 'shared_accounts.commercial_preview'
COMMERCE_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS shared_commercial_terms (
        account_id TEXT PRIMARY KEY REFERENCES shared_accounts(id),
        settings TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS shared_commercial_quotes (
        id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES shared_accounts(id),
        snapshot TEXT NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS shared_commercial_audit (
        id TEXT PRIMARY KEY, actor_platform TEXT NOT NULL, actor_external_id BIGINT,
        account_id TEXT, event TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
        before_state TEXT NOT NULL, after_state TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)''',
)


async def ensure_commercial_schema(db) -> None:
    await ensure_schema(db)
    if db_backend.is_postgres():
        await db.execute('SELECT pg_advisory_xact_lock(?)', (80420161108,))
    else:
        await db.execute('BEGIN IMMEDIATE')
    try:
        execute = getattr(db, 'execute_native_ddl', db.execute)
        for statement in COMMERCE_SCHEMA:
            await execute(statement)
        for table in ('shared_commercial_quotes', 'shared_commercial_audit'):
            if db_backend.is_postgres():
                await execute(f'''CREATE OR REPLACE FUNCTION {table}_append_only()
                    RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                    RAISE EXCEPTION 'commercial history is append-only'; END; $$''')
                await execute(f'''DO $$ BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = '{table}_append_only_guard'
                        AND tgrelid = '{table}'::regclass) THEN
                        CREATE TRIGGER {table}_append_only_guard BEFORE UPDATE OR DELETE OR TRUNCATE ON {table}
                        FOR EACH STATEMENT EXECUTE FUNCTION {table}_append_only();
                    END IF; END $$''')
            else:
                for operation in ('UPDATE', 'DELETE'):
                    await execute(f'''CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()}
                        BEFORE {operation} ON {table}
                        BEGIN SELECT RAISE(ABORT, 'commercial history is append-only'); END''')
        await db.execute('INSERT INTO bot_settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO NOTHING',
                         (CATALOG_KEY, json.dumps(Catalog().payload())))
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def lock_catalog(db) -> Catalog:
    suffix = ' FOR UPDATE' if db_backend.is_postgres() else ''
    row = await (await db.execute('SELECT value FROM bot_settings WHERE key = ?' + suffix, (CATALOG_KEY,))).fetchone()
    return Catalog.parse(json.loads(row[0]))


async def audit(db, actor, account_id: str | None, event: str, before: dict, after: dict, reason: str = '') -> None:
    await db.execute('''INSERT INTO shared_commercial_audit
        (id, actor_platform, actor_external_id, account_id, event, reason, before_state, after_state)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                     (uuid4().hex, actor.platform if actor else 'system', actor.external_id if actor else None,
                      account_id, event, reason, json.dumps(before), json.dumps(after)))


class CommercialStore:
    @asynccontextmanager
    async def transaction(self):
        async with db_backend.connect() as db:
            await ensure_commercial_schema(db)
            if not db_backend.is_postgres():
                await db.execute('BEGIN IMMEDIATE')
            try:
                catalog = await lock_catalog(db)
                yield db, catalog
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def catalog(self) -> Catalog:
        async with self.transaction() as (_, catalog):
            return catalog

    async def save_catalog(self, actor, changes: dict, expected_revision: int) -> Catalog:
        if type(expected_revision) is not int or expected_revision < 0:
            raise CommercialValidation('Некорректная версия настроек.')
        if not isinstance(changes, dict) or 'revision' in changes:
            raise CommercialValidation('Версия управляется сервером.')
        async with self.transaction() as (db, before):
            if expected_revision != before.revision:
                raise PreviewConflict('Commercial settings changed; reload before saving')
            after = Catalog.parse(before.payload() | changes | {'revision': before.revision + 1})
            # Catalog lock also serializes assignments and merges. Referenced
            # tariffs/groups cannot disappear underneath an existing account.
            rows = await (await db.execute('SELECT settings FROM shared_commercial_terms')).fetchall()
            for row in rows:
                Terms.parse(json.loads(row[0])).effective(after)
            await db.execute('UPDATE bot_settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?',
                             (json.dumps(after.payload()), CATALOG_KEY))
            await audit(db, actor, None, 'catalog_updated', before.payload(), after.payload())
            return after

    async def _account(self, db, account_id: str) -> str:
        account_id = await canonical_account(db, account_id)
        suffix = ' FOR UPDATE' if db_backend.is_postgres() else ''
        row = await (await db.execute('SELECT status FROM shared_accounts WHERE id = ?' + suffix, (account_id,))).fetchone()
        if not row or row[0] != 'active':
            raise PreviewConflict('Account changed; reload before saving')
        return account_id

    async def terms(self, account_id: str) -> dict:
        async with self.transaction() as (db, catalog):
            account_id = await self._account(db, account_id)
            terms = await load_terms(db, account_id)
            return {'account_id': account_id, 'settings': terms.payload(), 'effective': terms.effective(catalog)}

    async def find_account(self, platform: str, external_id: int) -> dict:
        async with self.transaction() as (db, catalog):
            row = await (await db.execute('SELECT account_id FROM shared_account_identities WHERE platform = ? AND external_id = ?', (platform, external_id))).fetchone()
            if not row:
                raise CommercialValidation('Аккаунт ещё не входил в общую Mini App.')
            account_id = await self._account(db, row[0])
            terms = await load_terms(db, account_id)
            return {'account_id': account_id, 'settings': terms.payload(), 'effective': terms.effective(catalog)}

    async def save_terms(self, actor, account_id: str, changes: dict, expected_revision: int) -> dict:
        if type(expected_revision) is not int or expected_revision < 0 or not isinstance(changes, dict) or 'revision' in changes:
            raise CommercialValidation('Некорректные условия или версия.')
        async with self.transaction() as (db, catalog):
            account_id = await self._account(db, account_id)
            before = await load_terms(db, account_id)
            if before.revision != expected_revision:
                raise PreviewConflict('Individual terms changed; reload before saving')
            after = Terms.parse(before.payload() | changes | {'revision': before.revision + 1})
            effective = after.effective(catalog)
            await db.execute('''INSERT INTO shared_commercial_terms(account_id, settings) VALUES (?, ?)
                ON CONFLICT(account_id) DO UPDATE SET settings = excluded.settings''', (account_id, json.dumps(after.payload())))
            await audit(db, actor, account_id, 'terms_updated', before.payload(), after.payload())
            return {'account_id': account_id, 'settings': after.payload(), 'effective': effective}

    async def quote(self, account, price_key: str, quantity: int) -> dict:
        key(price_key)
        if type(quantity) is not int or not 1 <= quantity <= 2**31 - 1:
            raise CommercialValidation('Количество должно быть положительным целым числом.')
        async with self.transaction() as (db, catalog):
            account_id = await self._account(db, account.id)
            terms = await load_terms(db, account_id)
            effective = terms.effective(catalog)
            tariff = catalog.tariffs.get(effective['tariff_id'], {})
            price = tariff.get('prices', {}).get(price_key)
            if price is None:
                raise CommercialValidation('Для этого тарифа цена ещё не настроена.')
            if price['unit'] == 'job' and quantity != 1:
                raise CommercialValidation('Цена за генерацию рассчитывается для одного запуска.')
            total = units(price['amount'], 4) * quantity
            formatted = exact(f'{total // 10000}.{total % 10000:04d}', 4)
            snapshot = {'id': uuid4().hex, 'scope': 'preview', 'account_id': account_id,
                        'platform': account.identity.platform, 'catalog_revision': catalog.revision,
                        'terms_revision': terms.revision, 'price_key': price_key, 'quantity': quantity,
                        'unit': price['unit'], 'unit_price': price['amount'], 'total': formatted,
                        'terms': effective, 'allowed_payment_providers': payment_methods(account.identity.platform)}
            await db.execute('INSERT INTO shared_commercial_quotes(id, account_id, snapshot) VALUES (?, ?, ?)',
                             (snapshot['id'], account_id, json.dumps(snapshot)))
            return snapshot

    async def get_quote(self, account_id: str, quote_id: str) -> dict:
        async with self.transaction() as (db, _):
            account_id = await self._account(db, account_id)
            row = await (await db.execute('SELECT account_id, snapshot FROM shared_commercial_quotes WHERE id = ?', (quote_id,))).fetchone()
            if not row or await canonical_account(db, row[0]) != account_id:
                raise PermissionError('Quote does not belong to this account')
            return json.loads(row[1])


async def load_terms(db, account_id: str) -> Terms:
    row = await (await db.execute('SELECT settings FROM shared_commercial_terms WHERE account_id = ?', (account_id,))).fetchone()
    return Terms.parse(json.loads(row[0])) if row else Terms()


async def merge_commercial_terms(db, canonical: str, other: str, link_id: str) -> None:
    before = await load_terms(db, canonical)
    incoming = await load_terms(db, other)
    left, right = before.payload(), incoming.payload()
    left.pop('revision')
    right.pop('revision')
    empty = Terms().payload()
    empty.pop('revision')
    if left != empty and right != empty and left != right:
        raise PreviewConflict('Individual commercial terms conflict; administrator reconciliation required')
    # Every merge invalidates edits opened under either account's old revision,
    # including explicitly saved empty/default assignments on the losing alias.
    after = Terms.parse((right if left == empty else left) | {'revision': max(before.revision, incoming.revision) + 1})
    await db.execute('''INSERT INTO shared_commercial_terms(account_id, settings) VALUES (?, ?)
        ON CONFLICT(account_id) DO UPDATE SET settings = excluded.settings''', (canonical, json.dumps(after.payload())))
    await audit(db, None, canonical, 'terms_merged', before.payload(), after.payload(), link_id)
    await db.execute('DELETE FROM shared_commercial_terms WHERE account_id = ?', (other,))
