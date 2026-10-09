"""Creator membership changes are authorized, independent and auditable."""
import asyncio
import json

import pytest

from bot import creator_tariff_membership as membership
from bot import database
from bot import db as db_backend

ADMIN = 999999999
TARGET = 12345678


async def rows(sql, parameters=()):
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        return [dict(row) for row in await (await db.execute(sql, parameters)).fetchall()]


@pytest.mark.asyncio
async def test_membership_defaults_false_and_rejects_unknown_target():
    assert await membership.get_creator_tariff_membership(TARGET) is False
    with pytest.raises(membership.CreatorTariffMembershipError, match="not found"):
        await membership.set_creator_tariff_membership(ADMIN, TARGET, True)
    assert await rows("SELECT * FROM creator_tariff_audit") == []


@pytest.mark.asyncio
async def test_non_admin_cannot_change_membership():
    await database.get_or_create_user(TARGET)
    with pytest.raises(PermissionError):
        await membership.set_creator_tariff_membership(TARGET, TARGET, True)
    assert not await membership.get_creator_tariff_membership(TARGET)
    assert await rows("SELECT * FROM creator_tariff_audit") == []


@pytest.mark.asyncio
async def test_grant_revoke_preserves_user_balance_and_admin_status():
    await database.get_or_create_user(TARGET)
    before = await rows("SELECT * FROM users WHERE telegram_id = ?", (TARGET,))
    grant = await membership.set_creator_tariff_membership(ADMIN, TARGET, True)
    assert grant["changed"] and grant["enabled"] and not grant["previous_enabled"]
    assert await membership.get_creator_tariff_membership(TARGET)
    assert not membership.config.is_admin(TARGET)
    repeated = await membership.set_creator_tariff_membership(ADMIN, TARGET, True)
    assert repeated["changed"] is False
    revoke = await membership.set_creator_tariff_membership(ADMIN, TARGET, False)
    assert revoke["changed"] and not revoke["enabled"] and revoke["previous_enabled"]
    assert not await membership.get_creator_tariff_membership(TARGET)
    assert await rows("SELECT * FROM users WHERE telegram_id = ?", (TARGET,)) == before
    audit = await rows("SELECT * FROM creator_tariff_audit ORDER BY created_at, id")
    assert len(audit) == 2
    assert {json.loads(row["before_state"])["enabled"] for row in audit} == {False, True}
    assert {json.loads(row["after_state"])["enabled"] for row in audit} == {False, True}
    assert all(row["actor_telegram_id"] == ADMIN and row["target_telegram_id"] == TARGET for row in audit)
    assert all(row["created_at"] for row in audit)


@pytest.mark.asyncio
async def test_duplicate_concurrent_grants_are_one_change():
    await database.get_or_create_user(TARGET)
    results = await asyncio.gather(*[
        membership.set_creator_tariff_membership(ADMIN, TARGET, True) for _ in range(5)
    ])
    assert sum(result["changed"] for result in results) == 1
    assert len(await rows("SELECT * FROM creator_tariff_audit")) == 1


@pytest.mark.asyncio
async def test_failed_audit_rolls_back_membership(monkeypatch):
    await database.get_or_create_user(TARGET)

    async def failed_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(membership, "_append_audit", failed_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await membership.set_creator_tariff_membership(ADMIN, TARGET, True)
    assert not await membership.get_creator_tariff_membership(TARGET)


@pytest.mark.asyncio
@pytest.mark.parametrize("sql", ["DELETE FROM creator_tariff_audit", "UPDATE creator_tariff_audit SET actor_telegram_id = 1"])
async def test_audit_is_append_only(sql):
    await database.get_or_create_user(TARGET)
    await membership.set_creator_tariff_membership(ADMIN, TARGET, True)
    with pytest.raises((db_backend.IntegrityError, db_backend.OperationalError), match="append.only"):
        async with db_backend.connect() as db:
            await db.execute(sql)
            await db.commit()
    assert len(await rows("SELECT * FROM creator_tariff_audit")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("target,enabled", [(True, True), (0, True), (-1, True), ("12", True), (2**63, True), (TARGET, 1), (TARGET, "false")])
async def test_membership_validates_input(target, enabled):
    with pytest.raises(ValueError):
        await membership.set_creator_tariff_membership(ADMIN, target, enabled)


@pytest.mark.asyncio
async def test_schema_is_idempotent():
    async with db_backend.connect() as db:
        await membership.ensure_creator_tariff_schema(db)
        await membership.ensure_creator_tariff_schema(db)
        await db.commit()


@pytest.mark.asyncio
async def test_expected_membership_is_checked_under_transaction_lock():
    await database.get_or_create_user(TARGET)
    await membership.set_creator_tariff_membership(ADMIN, TARGET, True)
    with pytest.raises(membership.CreatorTariffMembershipError, match="changed"):
        await membership.set_creator_tariff_membership(ADMIN, TARGET, False, expected_enabled=False)
    assert await membership.get_creator_tariff_membership(TARGET)
    assert len(await rows("SELECT * FROM creator_tariff_audit")) == 1


@pytest.mark.asyncio
async def test_config_audit_requires_admin_and_cannot_be_mutated():
    with pytest.raises(PermissionError):
        await membership.record_creator_tariff_config_audit(TARGET, {}, {"enabled": False})
    assert not await rows("SELECT * FROM creator_tariff_audit")
    event_id = await membership.record_creator_tariff_config_audit(ADMIN, {}, {"enabled": False})
    event = (await rows("SELECT * FROM creator_tariff_audit"))[0]
    assert event["id"] == event_id and event["target_telegram_id"] is None
    assert event["event_type"] == "config_updated"


@pytest.mark.asyncio
async def test_postgres_schema_uses_native_ddl_not_sqlite_translation(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    db = SimpleNamespace(execute=AsyncMock(), execute_native_ddl=AsyncMock())
    monkeypatch.setattr(db_backend, "is_postgres", lambda: True)
    await membership.ensure_creator_tariff_schema(db)
    db.execute.assert_not_awaited()
    statements = [call.args[0] for call in db.execute_native_ddl.await_args_list]
    assert all(statement in statements for statement in membership.SCHEMA)
    assert any("BEFORE UPDATE OR DELETE" in statement for statement in statements)
    assert all("AUTOINCREMENT" not in statement and "RAISE(ABORT" not in statement for statement in statements)


@pytest.mark.asyncio
async def test_actual_postgres_adapter_executes_creator_native_schema(monkeypatch):
    from bot.postgres_aiosqlite import PostgresConnection

    statements = []

    class Cursor:
        rowcount = -1

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, statement):
            statements.append(statement)

    class RawConnection:
        def cursor(self):
            return Cursor()

    monkeypatch.setattr(db_backend, "is_postgres", lambda: True)
    await membership.ensure_creator_tariff_schema(PostgresConnection(RawConnection()))
    assert statements == [*membership.SCHEMA, *membership.POSTGRES_AUDIT_GUARD]
