"""Audited per-recipient first-line rates; never alter balances or old invoices."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any
from uuid import uuid4

from bot import db as db_backend
from bot.config import config

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS partner_commission_settings (
        telegram_id BIGINT PRIMARY KEY REFERENCES users(telegram_id),
        first_line_basis_points INTEGER NOT NULL CHECK(first_line_basis_points >= 0 AND first_line_basis_points <= 10000 AND first_line_basis_points = CAST(first_line_basis_points AS INTEGER)),
        revision BIGINT NOT NULL CHECK(revision > 0),
        updated_by_telegram_id BIGINT NOT NULL,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS partner_commission_audit (
        id TEXT PRIMARY KEY,
        actor_telegram_id BIGINT NOT NULL,
        target_telegram_id BIGINT NOT NULL,
        before_state TEXT NOT NULL,
        after_state TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE INDEX IF NOT EXISTS idx_partner_commission_audit_target
       ON partner_commission_audit(target_telegram_id, created_at)""",
)
POSTGRES_AUDIT_GUARD = (
    """CREATE OR REPLACE FUNCTION partner_commission_audit_append_only()
       RETURNS trigger LANGUAGE plpgsql AS $$
       BEGIN RAISE EXCEPTION 'partner commission audit is append-only'; END;
       $$""",
    """DO $$ BEGIN
       IF NOT EXISTS (SELECT 1 FROM pg_trigger
           WHERE tgname = 'partner_commission_audit_append_only_guard'
           AND tgrelid = 'partner_commission_audit'::regclass) THEN
           CREATE TRIGGER partner_commission_audit_append_only_guard
           BEFORE UPDATE OR DELETE OR TRUNCATE ON partner_commission_audit
           FOR EACH STATEMENT EXECUTE FUNCTION partner_commission_audit_append_only();
       END IF;
       END $$""",
)


class PartnerCommissionError(ValueError):
    """Invalid rate, identity or missing target."""


class PartnerCommissionConflict(ValueError):
    """Another administrator changed the viewed revision."""


def _telegram_id(value: int) -> int:
    if type(value) is not int or not 0 < value < 2**63:
        raise PartnerCommissionError('Telegram ID must be a positive integer')
    return value


def _basis_points(value: float) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PartnerCommissionError('Percentage must be a number')
    try:
        number = Decimal(str(value))
        if not number.is_finite() or not 0 <= number <= 100:
            raise PartnerCommissionError('Percentage must be within 0–100')
        with localcontext() as decimal_context:
            decimal_context.prec = 64
            if number != number.quantize(Decimal('0.01')):
                raise PartnerCommissionError('Percentage supports at most two decimal places')
            return int(number * 100)
    except InvalidOperation as exc:
        raise PartnerCommissionError('Percentage must be a finite decimal') from exc


async def ensure_partner_commission_schema(db: Any) -> None:
    execute = getattr(db, 'execute_native_ddl', db.execute)
    for statement in SCHEMA:
        await execute(statement)
    if db_backend.is_postgres():
        for statement in POSTGRES_AUDIT_GUARD:
            await execute(statement)
    else:
        for operation in ('UPDATE', 'DELETE'):
            await execute(f"""CREATE TRIGGER IF NOT EXISTS partner_commission_audit_no_{operation.lower()}
                BEFORE {operation} ON partner_commission_audit
                BEGIN SELECT RAISE(ABORT, 'partner commission audit is append-only'); END""")


async def _read_setting(db, telegram_id: int, *, lock: bool = False) -> dict | None:
    from bot.partner_policy import get_partner_policy

    suffix = ' FOR UPDATE' if lock and db_backend.is_postgres() else ''
    user = await (await db.execute(
        'SELECT telegram_id, username, first_name FROM users WHERE telegram_id = ?' + suffix,
        (telegram_id,),
    )).fetchone()
    if user is None:
        return None
    row = await (await db.execute(
        'SELECT first_line_basis_points, revision FROM partner_commission_settings WHERE telegram_id = ?',
        (telegram_id,),
    )).fetchone()
    policy = get_partner_policy()
    return {
        'telegram_id': telegram_id, 'username': user[1], 'first_name': user[2],
        'effective_percent': int(row[0]) / 100 if row else policy.first_level_percent(telegram_id),
        'override_percent': int(row[0]) / 100 if row else None,
        'revision': int(row[1]) if row else 0,
        'source': 'admin' if row else 'configuration' if telegram_id in policy.level1_overrides else 'default',
    }


async def get_partner_commission_setting(telegram_id: int) -> dict | None:
    _telegram_id(telegram_id)
    async with db_backend.connect() as db:
        return await _read_setting(db, telegram_id)


async def effective_first_level_percent(db, telegram_id: int | None) -> float:
    from bot.partner_policy import get_partner_policy

    if telegram_id is None:
        return get_partner_policy().level1_percent
    setting = await _read_setting(db, int(telegram_id))
    return setting['effective_percent'] if setting else get_partner_policy().first_level_percent(telegram_id)


async def snapshot_first_line_overrides(db, payer_user_id: int, configured: dict[int, float]) -> dict[int, float]:
    """Freeze the actual payee's effective rate in the invoice transaction.

    The same recipient user lock serializes PostgreSQL admin changes and invoice
    capture. SQLite's existing invoice INSERT already holds the write lock.
    """
    suffix = ' FOR SHARE OF recipient' if db_backend.is_postgres() else ''
    row = await (await db.execute(
        'SELECT recipient.telegram_id FROM users payer JOIN users recipient '
        'ON recipient.id = payer.referred_by WHERE payer.id = ?' + suffix,
        (payer_user_id,),
    )).fetchone()
    result = dict(configured)
    overrides = await (await db.execute(
        "SELECT telegram_id, first_line_basis_points FROM partner_commission_settings",
    )).fetchall()
    result.update({int(value[0]): int(value[1]) / 100 for value in overrides})
    if row:
        result[int(row[0])] = await effective_first_level_percent(db, int(row[0]))
    return result


async def set_partner_commission_percent(
    actor_id: int, telegram_id: int, percent: float, *, expected_revision: int,
) -> dict:
    _telegram_id(actor_id)
    if not config.is_admin(actor_id):
        raise PermissionError('Partner percentage changes require administrator access')
    _telegram_id(telegram_id)
    basis_points = _basis_points(percent)
    percent = basis_points / 100
    if type(expected_revision) is not int or expected_revision < 0:
        raise PartnerCommissionError('Expected revision must be a nonnegative integer')
    async with db_backend.connect() as db:
        if not db_backend.is_postgres():
            await db.execute('BEGIN IMMEDIATE')
        try:
            before = await _read_setting(db, telegram_id, lock=True)
            if before is None:
                raise PartnerCommissionError('Existing user not found')
            if before['revision'] != expected_revision:
                raise PartnerCommissionConflict('Percentage changed; reload before saving')
            if before['override_percent'] == percent:
                await db.rollback()
                return {**before, 'changed': False}
            revision = expected_revision + 1
            await db.execute(
                """INSERT INTO partner_commission_settings
                   (telegram_id, first_line_basis_points, revision, updated_by_telegram_id)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(telegram_id) DO UPDATE SET
                   first_line_basis_points = excluded.first_line_basis_points,
                   revision = excluded.revision,
                   updated_by_telegram_id = excluded.updated_by_telegram_id,
                   updated_at = CURRENT_TIMESTAMP""",
                (telegram_id, basis_points, revision, actor_id),
            )
            after = {**before, 'effective_percent': percent, 'override_percent': percent,
                     'revision': revision, 'source': 'admin'}
            # Record only financial settings, not names or unrelated user data.
            def audit_state(value):
                return json.dumps({k: value[k] for k in ('effective_percent', 'override_percent', 'revision', 'source')}, sort_keys=True, allow_nan=False)
            await db.execute(
                """INSERT INTO partner_commission_audit
                   (id, actor_telegram_id, target_telegram_id, before_state, after_state)
                   VALUES (?, ?, ?, ?, ?)""",
                (uuid4().hex, actor_id, telegram_id, audit_state(before), audit_state(after)),
            )
            await db.commit()
            return {**after, 'changed': True}
        except Exception:
            await db.rollback()
            raise
