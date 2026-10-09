"""Independent, administrator-managed Seedance creator membership.

The user row is locked before reading membership, making change and immutable
attribution one transaction on SQLite and PostgreSQL. No user balance, role or
administrator configuration is ever changed here.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from bot import db as db_backend
from bot.config import config

logger = logging.getLogger(__name__)

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS creator_tariff_memberships (
        telegram_id BIGINT PRIMARY KEY REFERENCES users(telegram_id),
        enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
        updated_by_telegram_id BIGINT NOT NULL,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS creator_tariff_audit (
        id TEXT PRIMARY KEY,
        actor_telegram_id BIGINT NOT NULL,
        target_telegram_id BIGINT,
        event_type TEXT NOT NULL,
        before_state TEXT NOT NULL,
        after_state TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE INDEX IF NOT EXISTS idx_creator_tariff_audit_target
       ON creator_tariff_audit(target_telegram_id, created_at)""",
)
POSTGRES_AUDIT_GUARD = (
    """CREATE OR REPLACE FUNCTION creator_tariff_audit_append_only()
       RETURNS trigger LANGUAGE plpgsql AS $$
       BEGIN
           RAISE EXCEPTION 'creator tariff audit is append-only';
       END;
       $$""",
    """DO $$ BEGIN
       IF NOT EXISTS (
           SELECT 1 FROM pg_trigger WHERE tgname = 'creator_tariff_audit_append_only_guard'
           AND tgrelid = 'creator_tariff_audit'::regclass
       ) THEN
           CREATE TRIGGER creator_tariff_audit_append_only_guard
           BEFORE UPDATE OR DELETE OR TRUNCATE ON creator_tariff_audit
           FOR EACH STATEMENT EXECUTE FUNCTION creator_tariff_audit_append_only();
       END IF;
       END $$""",
)


class CreatorTariffMembershipError(ValueError):
    """Invalid or missing creator member target."""


def _telegram_id(value: int) -> int:
    if type(value) is not int or not 0 < value < 2**63:
        raise CreatorTariffMembershipError("Telegram ID must be a positive integer")
    return value


def _require_admin(actor_id: int) -> None:
    _telegram_id(actor_id)
    if not config.is_admin(actor_id):
        raise PermissionError("Creator tariff changes require administrator access")


async def ensure_creator_tariff_schema(db: Any) -> None:
    """Additive, idempotent schema used by init_db and clean deployments."""
    execute = getattr(db, "execute_native_ddl", db.execute)
    for statement in SCHEMA:
        await execute(statement)
    if db_backend.is_postgres():
        for statement in POSTGRES_AUDIT_GUARD:
            await execute(statement)
    else:
        for operation in ("UPDATE", "DELETE"):
            await execute(f"""CREATE TRIGGER IF NOT EXISTS creator_tariff_audit_no_{operation.lower()}
                BEFORE {operation} ON creator_tariff_audit
                BEGIN SELECT RAISE(ABORT, 'creator tariff audit is append-only'); END""")


async def get_creator_tariff_membership(telegram_id: int) -> bool:
    """An absent membership is ordinary pricing, without creating a user."""
    _telegram_id(telegram_id)
    async with db_backend.connect() as db:
        row = await (await db.execute(
            "SELECT enabled FROM creator_tariff_memberships WHERE telegram_id = ?",
            (telegram_id,),
        )).fetchone()
    return bool(row and row[0] == 1)


async def _append_audit(
    db: Any, actor_id: int, telegram_id: int | None, event_type: str,
    before: dict, after: dict,
) -> str:
    event_id = uuid4().hex
    await db.execute(
        """INSERT INTO creator_tariff_audit
           (id, actor_telegram_id, target_telegram_id, event_type, before_state, after_state)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (event_id, actor_id, telegram_id, event_type,
         json.dumps(before, ensure_ascii=False, sort_keys=True, allow_nan=False),
         json.dumps(after, ensure_ascii=False, sort_keys=True, allow_nan=False)),
    )
    return event_id


async def record_creator_tariff_config_audit(
    actor_id: int, before: dict, after: dict, *, event_type: str = "config_updated",
) -> str:
    """Append a configuration attempt/result; JSON prices live in preset_manager."""
    _require_admin(actor_id)
    if event_type not in {"config_change_requested", "config_updated", "config_update_failed"}:
        raise ValueError("Unsupported creator configuration audit event")
    async with db_backend.connect() as db:
        event_id = await _append_audit(db, actor_id, None, event_type, before, after)
        await db.commit()
    return event_id


async def set_creator_tariff_membership(
    actor_id: int, telegram_id: int, enabled: bool, *, expected_enabled: bool | None = None,
) -> dict:
    _require_admin(actor_id)
    _telegram_id(telegram_id)
    if expected_enabled is not None and type(expected_enabled) is not bool:
        raise CreatorTariffMembershipError("Expected membership must be boolean")
    if type(enabled) is not bool:
        raise CreatorTariffMembershipError("Membership enabled must be boolean")
    async with db_backend.connect() as db:
        if not db_backend.is_postgres():
            await db.execute("BEGIN IMMEDIATE")
        try:
            suffix = " FOR UPDATE" if db_backend.is_postgres() else ""
            user = await (await db.execute(
                "SELECT id FROM users WHERE telegram_id = ?" + suffix, (telegram_id,),
            )).fetchone()
            if user is None:
                raise CreatorTariffMembershipError("Existing user not found")
            row = await (await db.execute(
                "SELECT enabled FROM creator_tariff_memberships WHERE telegram_id = ?",
                (telegram_id,),
            )).fetchone()
            previous_enabled = bool(row and row[0] == 1)
            if expected_enabled is not None and previous_enabled != expected_enabled:
                raise CreatorTariffMembershipError("Membership changed; reopen the user card")
            changed = previous_enabled != enabled
            event_id = None
            if changed:
                await db.execute(
                    """INSERT INTO creator_tariff_memberships
                       (telegram_id, enabled, updated_by_telegram_id)
                       VALUES (?, ?, ?)
                       ON CONFLICT(telegram_id) DO UPDATE SET
                           enabled = excluded.enabled,
                           updated_by_telegram_id = excluded.updated_by_telegram_id,
                           updated_at = CURRENT_TIMESTAMP""",
                    (telegram_id, int(enabled), actor_id),
                )
                event_id = await _append_audit(
                    db, actor_id, telegram_id, "membership_updated",
                    {"enabled": previous_enabled}, {"enabled": enabled},
                )
            await db.commit()
        except BaseException:
            await db.rollback()
            raise
    if changed:
        logger.info(
            "creator_tariff_membership_updated actor=%s target=%s before=%s after=%s audit_id=%s",
            actor_id, telegram_id, previous_enabled, enabled, event_id,
        )
    return {
        "telegram_id": telegram_id, "enabled": enabled,
        "previous_enabled": previous_enabled, "changed": changed, "audit_id": event_id,
    }
