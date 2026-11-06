"""Exact, transactional wallet operations; sandbox funds never become live funds."""
from __future__ import annotations

import hashlib
import json
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext

from bot import db as db_backend

from .errors import PreviewConflict
from .reconciliation import reconcile_in_transaction
from .schema import ensure_schema

UNITS_PER_BANANA = 10000  # Immutable currency precision, not an economic rate.
MAX_UNITS = 2**63 - 1


class WalletConflict(PreviewConflict):
    """A key was reused with another request or a reservation is already settled."""


class InsufficientFunds(ValueError):
    """Available funds cannot cover the requested reservation."""


def amount_units(amount: str | int | Decimal) -> int:
    if isinstance(amount, bool) or not isinstance(amount, (str, int, Decimal)):
        raise TypeError('Use an exact decimal amount')
    try:
        value = Decimal(amount)
        if not value.is_finite() or value <= 0:
            raise ValueError('Amount must be positive and finite')
        if value < Decimal('0.0001') or value > MAX_UNITS:
            raise ValueError('Amount exceeds currency precision or capacity')
        with localcontext() as context:
            context.prec = max(64, len(value.as_tuple().digits) + 8)
            units = value * UNITS_PER_BANANA
            if units != units.to_integral_value() or units > MAX_UNITS:
                raise ValueError('Amount exceeds currency precision or capacity')
            return int(units)
    except InvalidOperation as exc:
        raise ValueError('Invalid decimal amount') from exc


def format_units(units: int) -> str:
    # Avoid both binary floating point and ambient Decimal rounding contexts.
    return f'{units // UNITS_PER_BANANA}.{units % UNITS_PER_BANANA:04d}'


@dataclass(frozen=True)
class Balance:
    available_units: int = 0
    reserved_units: int = 0
    revision: int = 0

    def payload(self) -> dict:
        return {'available': format_units(self.available_units), 'reserved': format_units(self.reserved_units), 'revision': self.revision}


WALLET_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS shared_wallets (
        scope TEXT NOT NULL CHECK(scope IN ('sandbox', 'live')),
        account_id TEXT NOT NULL REFERENCES shared_accounts(id),
        available_units BIGINT NOT NULL DEFAULT 0 CHECK(available_units >= 0),
        reserved_units BIGINT NOT NULL DEFAULT 0 CHECK(reserved_units >= 0),
        revision BIGINT NOT NULL DEFAULT 0 CHECK(revision >= 0),
        PRIMARY KEY(scope, account_id),
        CHECK(available_units <= 9223372036854775807 - reserved_units))''',
    '''CREATE TABLE IF NOT EXISTS shared_wallet_entries (
        scope TEXT NOT NULL,
        operation_key TEXT NOT NULL,
        account_id TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('opening', 'credit', 'reserve', 'capture', 'release', 'refund', 'transfer_in', 'transfer_out')),
        amount_units BIGINT NOT NULL CHECK(amount_units > 0),
        reference_key TEXT NOT NULL DEFAULT '',
        available_delta BIGINT NOT NULL,
        reserved_delta BIGINT NOT NULL,
        available_after BIGINT NOT NULL CHECK(available_after >= 0),
        reserved_after BIGINT NOT NULL CHECK(reserved_after >= 0),
        sequence BIGINT NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(scope, operation_key), UNIQUE(scope, account_id, sequence),
        FOREIGN KEY(scope, account_id) REFERENCES shared_wallets(scope, account_id))''',
    '''CREATE TABLE IF NOT EXISTS shared_wallet_reservations (
        scope TEXT NOT NULL,
        reservation_key TEXT NOT NULL,
        account_id TEXT NOT NULL,
        amount_units BIGINT NOT NULL CHECK(amount_units > 0),
        captured_units BIGINT NOT NULL DEFAULT 0 CHECK(captured_units >= 0),
        released_units BIGINT NOT NULL DEFAULT 0 CHECK(released_units >= 0),
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(scope, reservation_key),
        FOREIGN KEY(scope, account_id) REFERENCES shared_wallets(scope, account_id),
        CHECK(released_units <= amount_units AND captured_units <= amount_units - released_units))''',
    '''CREATE TABLE IF NOT EXISTS shared_wallet_opening_claims (
        scope TEXT NOT NULL CHECK(scope = 'sandbox'),
        platform TEXT NOT NULL CHECK(platform IN ('telegram', 'vk')),
        external_id BIGINT NOT NULL CHECK(external_id > 0),
        account_id TEXT NOT NULL REFERENCES shared_accounts(id),
        request_hash TEXT NOT NULL,
        snapshot_id TEXT NOT NULL,
        evidence_hash TEXT NOT NULL,
        amount_units BIGINT NOT NULL CHECK(amount_units >= 0),
        operation_key TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(scope, platform, external_id),
        FOREIGN KEY(scope, operation_key) REFERENCES shared_wallet_entries(scope, operation_key))''',
)


async def ensure_wallet_schema(db) -> None:
    await ensure_schema(db)
    if db_backend.is_postgres():
        await db.execute('SELECT pg_advisory_xact_lock(?)', (80420161106,))
    else:
        await db.execute('BEGIN IMMEDIATE')
    try:
        execute = getattr(db, 'execute_native_ddl', db.execute)
        for statement in WALLET_SCHEMA:
            await execute(statement)
        if db_backend.is_postgres():
            await execute('''CREATE OR REPLACE FUNCTION shared_wallet_entries_append_only()
                RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                RAISE EXCEPTION 'wallet ledger is append-only'; END; $$''')
            await execute('''DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_trigger
                    WHERE tgname = 'shared_wallet_entries_append_only_guard'
                    AND tgrelid = 'shared_wallet_entries'::regclass) THEN
                    CREATE TRIGGER shared_wallet_entries_append_only_guard
                    BEFORE UPDATE OR DELETE OR TRUNCATE ON shared_wallet_entries
                    FOR EACH STATEMENT EXECUTE FUNCTION shared_wallet_entries_append_only();
                END IF; END $$''')
        else:
            for operation in ('UPDATE', 'DELETE'):
                await execute(f'''CREATE TRIGGER IF NOT EXISTS shared_wallet_entries_no_{operation.lower()}
                    BEFORE {operation} ON shared_wallet_entries
                    BEGIN SELECT RAISE(ABORT, 'wallet ledger is append-only'); END''')
        if db_backend.is_postgres():
            await execute('''DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_trigger
                    WHERE tgname = 'shared_wallet_opening_claims_append_only_guard'
                    AND tgrelid = 'shared_wallet_opening_claims'::regclass) THEN
                    CREATE TRIGGER shared_wallet_opening_claims_append_only_guard
                    BEFORE UPDATE OR DELETE OR TRUNCATE ON shared_wallet_opening_claims
                    FOR EACH STATEMENT EXECUTE FUNCTION shared_wallet_entries_append_only();
                END IF; END $$''')
        else:
            for operation in ('UPDATE', 'DELETE'):
                await execute(f'''CREATE TRIGGER IF NOT EXISTS shared_wallet_opening_claims_no_{operation.lower()}
                    BEFORE {operation} ON shared_wallet_opening_claims
                    BEGIN SELECT RAISE(ABORT, 'opening claims are append-only'); END''')
        await db.commit()
    except Exception:
        await db.rollback()
        raise


def _key(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9:._/-]{1,160}', value):
        raise ValueError('Invalid operation key')
    return value


def _fingerprint(account_id: str, kind: str, units: int, reference: str) -> str:
    # Ownership is checked separately, so callbacks remain replayable after a merge.
    return hashlib.sha256(json.dumps([kind, units, reference], separators=(',', ':')).encode()).hexdigest()


async def canonical_account(db, account_id: str) -> str:
    seen = set()
    for _ in range(32):
        if account_id in seen:
            raise WalletConflict('Account alias cycle')
        seen.add(account_id)
        row = await (await db.execute('SELECT status, merged_into FROM shared_accounts WHERE id = ?', (account_id,))).fetchone()
        if not row:
            raise PermissionError('Account is not available')
        if row[0] == 'merged' and row[1]:
            account_id = row[1]
            continue
        if row[0] != 'active':
            raise PermissionError('Account is not available')
        return account_id
    raise WalletConflict('Account alias chain is too long')


def _receipt(row) -> dict:
    return {'operation_key': row[0], 'kind': row[1], 'amount': format_units(int(row[2])),
            'reference_key': row[3], 'sequence': int(row[4])}


class WalletService:
    def __init__(self, scope: str):
        if scope not in {'sandbox', 'live'}:
            raise ValueError('Invalid wallet scope')
        self.scope = scope

    @asynccontextmanager
    async def _transaction(self, account_id: str, operation_key: str | None = None):
        async with db_backend.connect() as db:
            await ensure_wallet_schema(db)
            if not db_backend.is_postgres():
                await db.execute('BEGIN IMMEDIATE')
            try:
                if operation_key and db_backend.is_postgres():
                    lock = int.from_bytes(hashlib.sha256(f'{self.scope}:{operation_key}'.encode()).digest()[:8], 'big', signed=True)
                    await db.execute('SELECT pg_advisory_xact_lock(?)', (lock,))
                suffix = ' FOR UPDATE' if db_backend.is_postgres() else ''
                # Lock only the canonical row. If a concurrent merge wins, restart
                # instead of taking another account lock in the opposite order.
                for _ in range(32):
                    account_id = await canonical_account(db, account_id)
                    account = await (await db.execute('SELECT status FROM shared_accounts WHERE id = ?' + suffix, (account_id,))).fetchone()
                    if account and account[0] == 'active':
                        break
                    await db.rollback()
                    if not db_backend.is_postgres():
                        await db.execute('BEGIN IMMEDIATE')
                    elif operation_key:
                        await db.execute('SELECT pg_advisory_xact_lock(?)', (lock,))
                else:
                    raise WalletConflict('Account changed; retry operation')
                await db.execute('INSERT INTO shared_wallets(scope, account_id) VALUES (?, ?) ON CONFLICT(scope, account_id) DO NOTHING',
                                 (self.scope, account_id))
                row = await (await db.execute('SELECT available_units, reserved_units, revision FROM shared_wallets WHERE scope = ? AND account_id = ?' + suffix,
                                             (self.scope, account_id))).fetchone()
                yield db, Balance(int(row[0]), int(row[1]), int(row[2])), account_id
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def snapshot(self, requested_account_id: str) -> dict:
        async with self._transaction(requested_account_id) as (db, balance, account_id):
            rows = await (await db.execute('''WITH RECURSIVE owned(id) AS (
                SELECT ? UNION ALL SELECT a.id FROM shared_accounts a JOIN owned o ON a.merged_into = o.id WHERE a.status = 'merged')
                SELECT operation_key, kind, amount_units, reference_key, sequence
                FROM shared_wallet_entries WHERE scope = ? AND account_id IN (SELECT id FROM owned)
                ORDER BY created_at DESC, operation_key DESC LIMIT 100''',
                                          (account_id, self.scope))).fetchall()
            return {'scope': self.scope, 'balance': balance.payload(), 'entries': [_receipt(row) for row in rows]}

    async def _replay(self, db, account_id: str, key: str, request_hash: str) -> dict | None:
        row = await (await db.execute('''SELECT operation_key, kind, amount_units, reference_key, sequence, account_id, request_hash
            FROM shared_wallet_entries WHERE scope = ? AND operation_key = ?''', (self.scope, key))).fetchone()
        if not row:
            return None
        if await canonical_account(db, row[5]) != account_id or row[6] != request_hash:
            raise WalletConflict('Operation key belongs to another request')
        return _receipt(row)

    async def reconcile(self, requested_account_id: str) -> dict:
        async with self._transaction(requested_account_id) as (db, balance, account_id):
            return await reconcile_in_transaction(db, self.scope, account_id, balance)

    async def _append(self, db, account_id: str, before: Balance, key: str, kind: str,
                      units: int, reference: str, available_delta: int, reserved_delta: int) -> dict:
        after = Balance(before.available_units + available_delta, before.reserved_units + reserved_delta, before.revision + 1)
        if min(after.available_units, after.reserved_units) < 0 or after.available_units + after.reserved_units > MAX_UNITS:
            raise ValueError('Wallet capacity exceeded')
        await db.execute('UPDATE shared_wallets SET available_units = ?, reserved_units = ?, revision = ? WHERE scope = ? AND account_id = ?',
                         (after.available_units, after.reserved_units, after.revision, self.scope, account_id))
        await db.execute('''INSERT INTO shared_wallet_entries(scope, operation_key, account_id, request_hash, kind, amount_units,
            reference_key, available_delta, reserved_delta, available_after, reserved_after, sequence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                         (self.scope, key, account_id, _fingerprint(account_id, kind, units, reference), kind, units, reference,
                          available_delta, reserved_delta, after.available_units, after.reserved_units, after.revision))
        return {'operation_key': key, 'kind': kind, 'amount': format_units(units), 'reference_key': reference, 'sequence': after.revision}

    async def apply(self, requested_account_id: str, kind: str, amount: str | int | Decimal,
                    operation_key: str, reference_key: str = '') -> dict:
        if kind not in {'credit', 'reserve', 'capture', 'release', 'refund'}:
            raise ValueError('Unknown wallet operation')
        units, key = amount_units(amount), _key(operation_key)
        if key.startswith(('link:', 'opening:')):
            raise ValueError('Reserved internal operation namespace')
        reference = _key(reference_key) if kind in {'capture', 'release', 'refund'} else ''
        if not reference and reference_key:
            raise ValueError('Unexpected operation reference')
        async with self._transaction(requested_account_id, key) as (db, balance, account_id):
            receipt = await self._replay(db, account_id, key, _fingerprint(account_id, kind, units, reference))
            if receipt:
                return {**receipt, 'replayed': True}
            available_delta, reserved_delta = 0, 0
            if kind == 'credit':
                available_delta = units
            elif kind == 'reserve':
                if balance.available_units < units:
                    raise InsufficientFunds('Insufficient available balance')
                await db.execute('INSERT INTO shared_wallet_reservations(scope, reservation_key, account_id, amount_units) VALUES (?, ?, ?, ?)',
                                 (self.scope, key, account_id, units))
                available_delta, reserved_delta = -units, units
            elif kind in {'capture', 'release'}:
                reservation = await (await db.execute('''SELECT account_id, amount_units, captured_units, released_units
                    FROM shared_wallet_reservations WHERE scope = ? AND reservation_key = ?''', (self.scope, reference))).fetchone()
                if not reservation or reservation[0] != account_id or units > int(reservation[1]) - int(reservation[2]) - int(reservation[3]):
                    raise WalletConflict('Reservation cannot cover this operation')
                column = 'captured_units' if kind == 'capture' else 'released_units'
                await db.execute(f'UPDATE shared_wallet_reservations SET {column} = {column} + ? WHERE scope = ? AND reservation_key = ?',
                                 (units, self.scope, reference))
                available_delta = units if kind == 'release' else 0
                reserved_delta = -units
            else:
                capture = await (await db.execute('''SELECT account_id, amount_units FROM shared_wallet_entries
                    WHERE scope = ? AND operation_key = ? AND kind = 'capture' ''', (self.scope, reference))).fetchone()
                refunded = await (await db.execute('''SELECT COALESCE(SUM(amount_units), 0) FROM shared_wallet_entries
                    WHERE scope = ? AND kind = 'refund' AND reference_key = ?''',
                                                   (self.scope, reference))).fetchone()
                if not capture or await canonical_account(db, capture[0]) != account_id or units > int(capture[1]) - int(refunded[0]):
                    raise WalletConflict('Refund exceeds the captured amount')
                available_delta = units
            receipt = await self._append(db, account_id, balance, key, kind, units, reference, available_delta, reserved_delta)
            return {**receipt, 'replayed': False}
