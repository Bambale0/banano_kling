"""Explicit internal TG credit freeze; never called by startup or public routes.

This is not live authority activation, an opening import or a settlement bridge.
Snapshots preserve raw storage values without choosing a normalization policy.
"""
from __future__ import annotations

import hashlib
import re
from uuid import uuid4

from bot import db as db_backend

from .schema import ensure_schema
from .wallet import WalletConflict, _key, canonical_account

FENCE_SCHEMA = '''CREATE TABLE IF NOT EXISTS shared_telegram_wallet_fences (
    id TEXT PRIMARY KEY,
    legacy_user_id BIGINT NOT NULL UNIQUE REFERENCES users(id),
    telegram_id BIGINT NOT NULL UNIQUE,
    account_id TEXT NOT NULL REFERENCES shared_accounts(id),
    source_lineage TEXT NOT NULL,
    operation_key TEXT NOT NULL UNIQUE,
    raw_balance TEXT NOT NULL,
    storage_type TEXT NOT NULL,
    guard_digest TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)'''


def _guard_statements(postgres: bool) -> list[str]:
    statements = []
    if postgres:
        statements.append('''CREATE OR REPLACE FUNCTION shared_telegram_credit_guard()
            RETURNS trigger LANGUAGE plpgsql SET search_path FROM CURRENT AS $$ BEGIN
            IF TG_OP = 'TRUNCATE' THEN
                RAISE EXCEPTION 'legacy wallet is frozen';
            END IF;
            IF TG_OP = 'DELETE' THEN
                IF OLD.shared_wallet_fence_id IS NOT NULL THEN
                    RAISE EXCEPTION 'legacy wallet is frozen';
                END IF;
                RETURN OLD;
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.shared_wallet_fence_id IS NOT NULL OR EXISTS (
                    SELECT 1 FROM shared_telegram_wallet_fences
                    WHERE legacy_user_id = NEW.id OR telegram_id = NEW.telegram_id) THEN
                    RAISE EXCEPTION 'legacy wallet is frozen';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.shared_wallet_fence_id IS NOT NULL AND (
                NEW.credits IS DISTINCT FROM OLD.credits OR
                NEW.id IS DISTINCT FROM OLD.id OR
                NEW.telegram_id IS DISTINCT FROM OLD.telegram_id OR
                NEW.shared_wallet_fence_id IS DISTINCT FROM OLD.shared_wallet_fence_id) THEN
                RAISE EXCEPTION 'legacy wallet is frozen';
            END IF;
            IF NEW.shared_wallet_fence_id IS NOT NULL AND OLD.shared_wallet_fence_id IS NULL AND (
                NEW.credits IS DISTINCT FROM OLD.credits OR NEW.id IS DISTINCT FROM OLD.id OR
                NEW.telegram_id IS DISTINCT FROM OLD.telegram_id OR NOT EXISTS (
                    SELECT 1 FROM shared_telegram_wallet_fences WHERE id = NEW.shared_wallet_fence_id
                    AND legacy_user_id = OLD.id AND telegram_id = OLD.telegram_id)) THEN
                RAISE EXCEPTION 'legacy wallet is frozen';
            END IF;
            RETURN NEW; END $$''')
        statements.append('''CREATE OR REPLACE FUNCTION shared_telegram_fence_immutable()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'wallet fence is immutable'; END $$''')
        for name, events, table, level, function in (
            ('shared_telegram_credit_rows', 'INSERT OR UPDATE OR DELETE', 'users', 'ROW', 'shared_telegram_credit_guard'),
            ('shared_telegram_credit_truncate', 'TRUNCATE', 'users', 'STATEMENT', 'shared_telegram_credit_guard'),
            ('shared_telegram_fence_rows', 'UPDATE OR DELETE OR TRUNCATE', 'shared_telegram_wallet_fences', 'STATEMENT', 'shared_telegram_fence_immutable'),
        ):
            statements.append(f'''DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger
                WHERE tgname = '{name}' AND tgrelid = '{table}'::regclass) THEN
                CREATE TRIGGER {name} BEFORE {events} ON {table}
                FOR EACH {level} EXECUTE FUNCTION {function}(); END IF; END $$''')
    else:
        guards = {
            'update': '''OLD.shared_wallet_fence_id IS NOT NULL AND (
                NEW.credits IS NOT OLD.credits OR NEW.id IS NOT OLD.id OR
                NEW.telegram_id IS NOT OLD.telegram_id OR
                NEW.shared_wallet_fence_id IS NOT OLD.shared_wallet_fence_id)
                OR (OLD.shared_wallet_fence_id IS NULL AND NEW.shared_wallet_fence_id IS NOT NULL AND (
                    NEW.credits IS NOT OLD.credits OR NEW.id IS NOT OLD.id OR
                    NEW.telegram_id IS NOT OLD.telegram_id OR NOT EXISTS (
                        SELECT 1 FROM shared_telegram_wallet_fences WHERE id = NEW.shared_wallet_fence_id
                        AND legacy_user_id = OLD.id AND telegram_id = OLD.telegram_id)))
                OR EXISTS (SELECT 1 FROM users frozen WHERE frozen.shared_wallet_fence_id IS NOT NULL
                    AND frozen.id != OLD.id AND (frozen.id = NEW.id OR frozen.telegram_id = NEW.telegram_id
                    OR frozen.referral_code = NEW.referral_code))''',
            'delete': 'OLD.shared_wallet_fence_id IS NOT NULL',
            'insert': '''NEW.shared_wallet_fence_id IS NOT NULL OR EXISTS (
                SELECT 1 FROM shared_telegram_wallet_fences
                WHERE legacy_user_id = NEW.id OR telegram_id = NEW.telegram_id)
                OR EXISTS (SELECT 1 FROM users frozen WHERE frozen.shared_wallet_fence_id IS NOT NULL
                    AND (frozen.id = NEW.id OR frozen.telegram_id = NEW.telegram_id
                    OR frozen.referral_code = NEW.referral_code))''',
        }
        for event, condition in guards.items():
            statements.append(f'''CREATE TRIGGER IF NOT EXISTS shared_telegram_credit_{event}
                BEFORE {event.upper()} ON users WHEN {condition}
                BEGIN SELECT RAISE(ROLLBACK, 'legacy wallet is frozen'); END''')
        for event in ('UPDATE', 'DELETE'):
            statements.append(f'''CREATE TRIGGER IF NOT EXISTS shared_telegram_fence_no_{event.lower()}
                BEFORE {event} ON shared_telegram_wallet_fences
                BEGIN SELECT RAISE(ROLLBACK, 'wallet fence is immutable'); END''')
        statements.append('''CREATE TRIGGER IF NOT EXISTS shared_telegram_fence_no_replace
            BEFORE INSERT ON shared_telegram_wallet_fences WHEN EXISTS (
                SELECT 1 FROM shared_telegram_wallet_fences WHERE id = NEW.id
                OR legacy_user_id = NEW.legacy_user_id OR telegram_id = NEW.telegram_id
                OR operation_key = NEW.operation_key)
            BEGIN SELECT RAISE(ROLLBACK, 'wallet fence is immutable'); END''')
    return statements


async def assert_fence_guards(db) -> str:
    """Fail closed on missing, disabled or stale guards; do not silently attest DDL."""
    statements = _guard_statements(db_backend.is_postgres())
    if db_backend.is_postgres():
        expected = {
            'shared_telegram_credit_rows': ('users', 31, 'shared_telegram_credit_guard'),
            'shared_telegram_credit_truncate': ('users', 34, 'shared_telegram_credit_guard'),
            'shared_telegram_fence_rows': ('shared_telegram_wallet_fences', 58, 'shared_telegram_fence_immutable'),
        }
        rows = await (await db.execute('''SELECT t.tgname, c.relname, t.tgtype, p.proname,
            t.tgenabled, pn.nspname = current_schema(), p.prosrc, p.prosecdef, p.proconfig,
            t.tgqual IS NULL AND t.tgnargs = 0 AND t.tgattr::text = ''
            FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_proc p ON p.oid = t.tgfoid JOIN pg_namespace pn ON pn.oid = p.pronamespace
            WHERE n.nspname = current_schema() AND NOT t.tgisinternal''')).fetchall()
        actual = {row[0]: row for row in rows}
        search_path = (await (await db.execute("SELECT current_setting('search_path')")).fetchone())[0]
        bodies = {re.search(r'FUNCTION (\w+)\(', sql)[1]: sql.split('$$')[1]
                  for sql in statements if sql.startswith('CREATE OR REPLACE FUNCTION')}
        for name, definition in expected.items():
            row = actual.get(name)
            if not row or tuple(row[i] for i in (1, 2, 3)) != definition or row[4] not in {'O', 'A'} or not row[5] or row[7] or not row[9]:
                raise WalletConflict('Legacy wallet fence guards are unavailable')
            if row[6] != bodies[definition[2]]:
                raise WalletConflict('Legacy wallet fence guard definition changed')
            if definition[2] == 'shared_telegram_credit_guard' and row[8] != ['search_path=' + search_path]:
                raise WalletConflict('Legacy wallet fence search path changed')
    else:
        rows = await (await db.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'")).fetchall()
        actual = {row[0]: row[1] for row in rows}
        for sql in statements:
            name = re.search(r'CREATE TRIGGER IF NOT EXISTS (\w+)', sql)[1]
            normalize = lambda value: ' '.join(value.replace('IF NOT EXISTS ', '').split())
            if name not in actual or normalize(actual[name]) != normalize(sql):
                raise WalletConflict('Legacy wallet fence guard definition changed')
    return hashlib.sha256('\n'.join(statements).encode()).hexdigest()


async def ensure_fence_schema(db) -> None:
    """Explicit maintenance preparation, never run inside a freeze transaction."""
    await ensure_schema(db)
    postgres = db_backend.is_postgres()
    await db.execute('SELECT pg_advisory_xact_lock(?)' if postgres else 'BEGIN IMMEDIATE',
                     (80420161109,) if postgres else ())
    execute = getattr(db, 'execute_native_ddl', db.execute)
    try:
        await execute(FENCE_SCHEMA)
        if postgres:
            await execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS shared_wallet_fence_id TEXT')
        else:
            columns = await (await db.execute('PRAGMA table_info(users)')).fetchall()
            if 'shared_wallet_fence_id' not in {row[1] for row in columns}:
                await execute('ALTER TABLE users ADD COLUMN shared_wallet_fence_id TEXT')
        for statement in _guard_statements(postgres):
            await execute(statement)
        await assert_fence_guards(db)
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def freeze_telegram_wallet(account_id: str, telegram_id: int,
                                 source_lineage: str, operation_key: str) -> dict:
    """Atomically freeze one owned legacy balance and return its private receipt.

    A lineage/key must come from a reviewed migration plan. Neither is proof of
    cross-platform draining or authorization to import money. No thaw is exposed.
    """
    if type(telegram_id) is not int or not 0 < telegram_id < 2**63:
        raise ValueError('Invalid Telegram identity')
    source_lineage, operation_key = _key(source_lineage), _key(operation_key)
    async with db_backend.connect() as db:
        # Preparation is an explicit separate operation. Repeating ALTER TABLE
        # here would wait on an older reader before we could prove MVCC fencing.
        if not db_backend.is_postgres():
            await db.execute('BEGIN IMMEDIATE')
        try:
            account_id = await canonical_account(db, account_id)
            suffix = ' FOR UPDATE' if db_backend.is_postgres() else ''
            identity = await (await db.execute(
                'SELECT account_id FROM shared_account_identities WHERE platform = ? AND external_id = ?' + suffix,
                ('telegram', telegram_id),
            )).fetchone()
            if not identity or await canonical_account(db, identity[0]) != account_id:
                raise PermissionError('Legacy wallet does not belong to this account')
            storage = 'pg_typeof(credits)::text' if db_backend.is_postgres() else 'typeof(credits)'
            user = await (await db.execute(
                f'SELECT id, credits, {storage}, shared_wallet_fence_id FROM users WHERE telegram_id = ?' + suffix,
                (telegram_id,),
            )).fetchone()
            if not user:
                raise PermissionError('Legacy wallet does not exist')
            previous = await (await db.execute('''SELECT id, raw_balance, storage_type, source_lineage,
                operation_key FROM shared_telegram_wallet_fences WHERE legacy_user_id = ?''', (user[0],))).fetchone()
            guard_digest = await assert_fence_guards(db)
            if previous:
                if previous[3] != source_lineage or previous[4] != operation_key or user[3] != previous[0]:
                    raise WalletConflict('Legacy wallet already has another freeze receipt')
                result = {'id': previous[0], 'raw_balance': previous[1], 'storage_type': previous[2], 'replayed': True}
            else:
                fence_id, raw = uuid4().hex, str(user[1])
                await db.execute('''INSERT INTO shared_telegram_wallet_fences
                    (id, legacy_user_id, telegram_id, account_id, source_lineage, operation_key, raw_balance, storage_type, guard_digest)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (fence_id, user[0], telegram_id, account_id, source_lineage, operation_key, raw, user[2], guard_digest))
                await db.execute('UPDATE users SET shared_wallet_fence_id = ? WHERE id = ?', (fence_id, user[0]))
                result = {'id': fence_id, 'raw_balance': raw, 'storage_type': user[2], 'replayed': False}
            await db.commit()
            return result
        except Exception:
            await db.rollback()
            raise
