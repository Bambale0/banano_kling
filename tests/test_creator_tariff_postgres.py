"""Creator tariff acceptance against an explicitly disposable PostgreSQL 16 DB.

Opt in with CREATOR_POSTGRES_TEST=1 and CREATOR_POSTGRES_TEST_DSN. Each test
owns a random schema; no production environment, pool, or data is accessed.
The regular suite skips these tests unless explicitly opted in.
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from bot import creator_tariff, database
from bot import creator_tariff_membership as membership
from bot import db as db_backend
from bot.config import config
from bot.postgres_aiosqlite import PostgresConnection
from bot.services.preset_manager import preset_manager

pytestmark = pytest.mark.skipif(
    os.environ.get("CREATOR_POSTGRES_TEST") != "1",
    reason="requires dedicated disposable creator PostgreSQL service",
)
ADMIN = 999999999
TARGET = 76543210
TEST_DB_NAME = "banano_creator_test"
TEST_DB_USER = "creator_test"


def validated_test_dsn(value: str) -> str:
    """Fail before connecting unless this is the explicitly named local test DB."""
    try:
        parameters = conninfo_to_dict(value)
    except psycopg.ProgrammingError:
        raise ValueError("Invalid disposable PostgreSQL connection string") from None
    allowed = {"host", "port", "dbname", "user", "password", "connect_timeout"}
    if set(parameters) - allowed:
        raise ValueError("Only explicit disposable test connection parameters are allowed")
    if parameters.get("host") not in {"127.0.0.1", "localhost"}:
        raise ValueError("Creator PostgreSQL tests require a loopback host")
    if parameters.get("dbname") != TEST_DB_NAME:
        raise ValueError("Creator PostgreSQL tests require their dedicated database")
    if parameters.get("user") != TEST_DB_USER or parameters.get("password") != TEST_DB_USER:
        raise ValueError("Creator PostgreSQL tests require disposable test credentials")
    if not str(parameters.get("port", "5432")).isdigit() or not 0 < int(parameters.get("port", "5432")) < 65536:
        raise ValueError("Invalid disposable PostgreSQL port")
    return value


async def connect_test_database(dsn, **kwargs):
    """Explicit address overrides inherited libpq host-address environment."""
    return await psycopg.AsyncConnection.connect(
        validated_test_dsn(dsn), host="127.0.0.1", hostaddr="127.0.0.1",
        connect_timeout=5, sslmode="disable", **kwargs,
    )


@pytest.fixture(autouse=True)
async def isolated_database():
    """Override the root SQLite/production-pool fixture for this module only."""
    yield


@pytest.fixture
async def pg(monkeypatch):
    dsn = validated_test_dsn(os.environ.get("CREATOR_POSTGRES_TEST_DSN", ""))
    schema = f"creator_test_{uuid4().hex}"
    async with await connect_test_database(dsn, autocommit=True) as owner:
        await owner.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        @asynccontextmanager
        async def raw():
            async with await connect_test_database(
                dsn,
                # Generated schema contains only a fixed prefix and UUID hex.
                options=f"-csearch_path={schema} -cstatement_timeout=10000 -clock_timeout=5000",
            ) as connection:
                yield connection

        @asynccontextmanager
        async def connect(*_args, **_kwargs):
            async with raw() as connection:
                yield PostgresConnection(connection)

        async def rows(statement, parameters=()):
            async with connect() as connection:
                cursor = await connection.execute(statement, parameters)
                return [dict(row) for row in await cursor.fetchall()]

        monkeypatch.setenv("DATABASE_URL", dsn)
        monkeypatch.setattr(db_backend, "connect", connect)
        monkeypatch.setattr(config, "is_admin", lambda user_id: user_id == ADMIN)
        assert db_backend.is_postgres()
        yield SimpleNamespace(raw=raw, connect=connect, rows=rows, schema=schema)
    finally:
        # Only the schema this fixture created can be dropped, in a DB whose
        # loopback host, database name and synthetic credentials were checked.
        async with await connect_test_database(dsn, autocommit=True) as owner:
            await owner.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
async def creator_db(pg):
    canonical_schema = Path(__file__).resolve().parents[1] / "schema_postgres.sql"
    async with pg.raw() as connection:
        await connection.execute(canonical_schema.read_text(encoding="utf-8"))
    async with pg.connect() as connection:
        await membership.ensure_creator_tariff_schema(connection)
        await connection.execute(
            "INSERT INTO users(telegram_id, credits) VALUES (?, ?), (?, ?)",
            (ADMIN, 100, TARGET, 100),
        )
        await connection.commit()
    return pg


@pytest.fixture
async def priced_creator(creator_db, monkeypatch):
    prices = deepcopy(preset_manager.get_price_config())
    prices["creator_tariff"] = {"enabled": True, "video_models": {
        model: {"quality_costs": {quality: 1.5 for quality in qualities}}
        for model, qualities in creator_tariff._required_qualities().items()
    }}
    monkeypatch.setattr(preset_manager, "_price_config", prices)
    await membership.set_creator_tariff_membership(ADMIN, TARGET, True)
    return creator_db


async def balance(pg):
    return float((await pg.rows("SELECT credits FROM users WHERE telegram_id = ?", (TARGET,)))[0]["credits"])


async def pending_task(pg, *, model="seedance_2_5", admin_free=False):
    quote = await creator_tariff.quote_video_for_actor(TARGET, model, 5, "720p")
    if not admin_free:
        assert quote.profile == "creator" and quote.charge_cost == 7.5
        assert await database.deduct_credits(TARGET, quote.charge_cost)
    user_id = (await pg.rows("SELECT id FROM users WHERE telegram_id = ?", (TARGET,)))[0]["id"]
    task_id = f"creator-pg-{uuid4().hex}"
    metadata = {
        "billing_quote": quote.to_dict(), "charged_cost": quote.charge_cost,
        "charged": not admin_free, "admin_free": admin_free,
        "refund_on_failure": not admin_free, "refund_claimed": False,
    }
    assert await database.add_generation_task(
        user_id, TARGET, task_id, "video", "creator-postgres-test", model=model,
        duration=5, aspect_ratio="16:9", prompt="Synthetic local regression",
        cost=quote.charge_cost, request_data=metadata,
    )
    row = (await pg.rows("SELECT * FROM generation_tasks WHERE task_id = ?", (task_id,)))[0]
    return row, quote.to_dict()


async def change_tariff_and_role(monkeypatch):
    await membership.set_creator_tariff_membership(ADMIN, TARGET, False)
    for model in preset_manager._price_config["creator_tariff"]["video_models"].values():
        model["quality_costs"] = dict.fromkeys(model["quality_costs"], 41)
    monkeypatch.setattr(config, "is_admin", lambda user_id: user_id in {ADMIN, TARGET})


async def test_legacy_user_schema_migration_is_additive_and_repeatable(pg):
    async with pg.connect() as connection:
        await connection.execute_native_ddl("""CREATE TABLE users (
            id BIGSERIAL PRIMARY KEY, telegram_id BIGINT UNIQUE NOT NULL,
            credits NUMERIC(12, 4) NOT NULL DEFAULT 0
        )""")
        await connection.execute("INSERT INTO users(telegram_id, credits) VALUES (?, ?)", (TARGET, 19.75))
        await membership.ensure_creator_tariff_schema(connection)
        await membership.ensure_creator_tariff_schema(connection)
        await connection.commit()
    assert not await membership.get_creator_tariff_membership(TARGET)
    assert await balance(pg) == 19.75
    assert await pg.rows("SELECT * FROM creator_tariff_memberships") == []
    assert await pg.rows("SELECT * FROM creator_tariff_audit") == []
    assert await membership.set_creator_tariff_membership(ADMIN, TARGET, True)
    assert await balance(pg) == 19.75


async def test_clean_schema_and_runtime_migration_agree(creator_db):
    async with creator_db.connect() as connection:
        await membership.ensure_creator_tariff_schema(connection)
        await membership.ensure_creator_tariff_schema(connection)
        await connection.commit()
    trigger = await creator_db.rows(
        "SELECT tgname FROM pg_trigger WHERE tgrelid = 'creator_tariff_audit'::regclass AND NOT tgisinternal"
    )
    assert [row["tgname"] for row in trigger] == ["creator_tariff_audit_append_only_guard"]
    await membership.set_creator_tariff_membership(ADMIN, TARGET, True)
    event = (await creator_db.rows("SELECT * FROM creator_tariff_audit"))[0]
    assert event["actor_telegram_id"] == ADMIN and event["target_telegram_id"] == TARGET
    assert json.loads(event["before_state"]) == {"enabled": False}
    assert json.loads(event["after_state"]) == {"enabled": True}
    assert event["created_at"]
    assert not config.is_admin(TARGET) and await balance(creator_db) == 100


async def test_membership_permissions_and_target_are_checked(creator_db):
    with pytest.raises(PermissionError):
        await membership.set_creator_tariff_membership(TARGET, TARGET, True)
    with pytest.raises(membership.CreatorTariffMembershipError, match="not found"):
        await membership.set_creator_tariff_membership(ADMIN, TARGET + 1, True)
    assert await creator_db.rows("SELECT * FROM creator_tariff_audit") == []
    assert await creator_db.rows("SELECT * FROM creator_tariff_memberships") == []


async def test_membership_and_audit_roll_back_on_database_audit_failure(creator_db):
    async with creator_db.connect() as connection:
        await connection.execute_native_ddl("""CREATE FUNCTION reject_test_creator_audit()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'synthetic audit failure'; END; $$""")
        await connection.execute_native_ddl("""CREATE TRIGGER reject_test_creator_audit
            BEFORE INSERT ON creator_tariff_audit FOR EACH STATEMENT
            EXECUTE FUNCTION reject_test_creator_audit()""")
        await connection.commit()
    with pytest.raises(db_backend.OperationalError, match="synthetic audit failure"):
        await membership.set_creator_tariff_membership(ADMIN, TARGET, True)
    assert not await membership.get_creator_tariff_membership(TARGET)
    assert await creator_db.rows("SELECT * FROM creator_tariff_audit") == []
    assert await balance(creator_db) == 100


@pytest.mark.parametrize("statement", [
    "UPDATE creator_tariff_audit SET actor_telegram_id = 1",
    "DELETE FROM creator_tariff_audit",
    "TRUNCATE creator_tariff_audit",
])
async def test_audit_is_immutable_in_postgres(creator_db, statement):
    await membership.set_creator_tariff_membership(ADMIN, TARGET, True)
    with pytest.raises(db_backend.OperationalError, match="append-only"):
        async with creator_db.connect() as connection:
            await connection.execute(statement)
            await connection.commit()
    assert len(await creator_db.rows("SELECT * FROM creator_tariff_audit")) == 1


async def test_concurrent_duplicate_grants_and_revokes_audit_once_each(creator_db):
    for enabled in (True, False):
        results = await asyncio.gather(*[
            membership.set_creator_tariff_membership(ADMIN, TARGET, enabled) for _ in range(8)
        ])
        assert sum(result["changed"] for result in results) == 1
        assert await membership.get_creator_tariff_membership(TARGET) is enabled
    assert len(await creator_db.rows("SELECT * FROM creator_tariff_audit")) == 2
    assert await balance(creator_db) == 100


async def test_concurrent_mixed_grant_revoke_has_a_serializable_audit(creator_db):
    results = await asyncio.gather(*[
        membership.set_creator_tariff_membership(ADMIN, TARGET, bool(index % 2)) for index in range(16)
    ])
    audit = await creator_db.rows("SELECT * FROM creator_tariff_audit")
    changed = [result for result in results if result["changed"]]
    assert len(audit) == len(changed)
    assert {row["id"] for row in audit} == {result["audit_id"] for result in changed}
    grants = sum(json.loads(row["after_state"])["enabled"] for row in audit)
    revokes = len(audit) - grants
    assert grants - revokes == int(await membership.get_creator_tariff_membership(TARGET))
    assert all(json.loads(row["before_state"])["enabled"] != json.loads(row["after_state"])["enabled"] for row in audit)
    assert await balance(creator_db) == 100


async def test_stale_confirmation_is_checked_after_postgres_lock(creator_db):
    results = await asyncio.gather(*[
        membership.set_creator_tariff_membership(ADMIN, TARGET, True, expected_enabled=False)
        for _ in range(8)
    ], return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
    assert all(isinstance(result, membership.CreatorTariffMembershipError) for result in results if isinstance(result, Exception))
    assert len(await creator_db.rows("SELECT * FROM creator_tariff_audit")) == 1


@pytest.mark.parametrize("model", ["seedance_2", "seedance_2_5"])
async def test_fractional_locked_quote_survives_changes_and_refunds_once(priced_creator, monkeypatch, model):
    from bot.services.task_watchdog import force_fail_task

    row, quote = await pending_task(priced_creator, model=model)
    assert await balance(priced_creator) == 92.5
    assert json.loads(row["request_data"])["billing_quote"] == quote
    await change_tariff_and_role(monkeypatch)
    results = await asyncio.gather(*[
        force_fail_task(row["id"], row["user_id"], 999, expected_provider_task_id=row["task_id"])
        for _ in range(8)
    ])
    assert results.count(True) == 1
    assert await balance(priced_creator) == 100
    final = (await priced_creator.rows("SELECT * FROM generation_tasks WHERE id = ?", (row["id"],)))[0]
    metadata = json.loads(final["request_data"])
    assert metadata["billing_quote"] == quote
    assert metadata["refund_claimed"] is True and metadata["refund_state"] == "refunded"
    assert final["status"] == "failed" and final["completed_at"]


async def test_webhook_and_watchdog_race_cannot_refund_twice(priced_creator, monkeypatch):
    from bot.handlers.seedance_25_public_release import _claim_async_refund
    from bot.services.task_watchdog import force_fail_task

    row, quote = await pending_task(priced_creator)
    await change_tariff_and_role(monkeypatch)
    results = await asyncio.gather(
        *[_claim_async_refund(row["task_id"]) for _ in range(4)],
        *[force_fail_task(row["id"], row["user_id"], 999, expected_provider_task_id=row["task_id"]) for _ in range(4)],
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, Exception):
            assert isinstance(result, RuntimeError) and "refund claim changed" in str(result)
    assert await _claim_async_refund(row["task_id"]) is None
    assert await balance(priced_creator) == 100
    final = (await priced_creator.rows("SELECT * FROM generation_tasks WHERE id = ?", (row["id"],)))[0]
    assert final["status"] == "failed"
    assert json.loads(final["request_data"])["billing_quote"] == quote


async def test_refund_user_failure_rolls_back_claim_and_status(priced_creator):
    from bot.services.task_watchdog import force_fail_task

    row, quote = await pending_task(priced_creator)
    with pytest.raises(RuntimeError, match="Refund user missing"):
        await force_fail_task(row["id"], -1, 999, expected_provider_task_id=row["task_id"])
    current = (await priced_creator.rows("SELECT * FROM generation_tasks WHERE id = ?", (row["id"],)))[0]
    assert current["status"] == "pending"
    assert json.loads(current["request_data"])["refund_claimed"] is False
    assert json.loads(current["request_data"])["billing_quote"] == quote
    assert await balance(priced_creator) == 92.5
    assert await force_fail_task(row["id"], row["user_id"], 999, expected_provider_task_id=row["task_id"])
    assert await balance(priced_creator) == 100


async def test_admin_free_locked_quote_never_refunds_nominal_price(priced_creator, monkeypatch):
    from bot.services.task_watchdog import force_fail_task

    monkeypatch.setattr(config, "is_admin", lambda user_id: user_id in {ADMIN, TARGET})
    row, quote = await pending_task(priced_creator, admin_free=True)
    assert quote["profile"] == "admin" and quote["charge_cost"] == 0
    monkeypatch.setattr(config, "is_admin", lambda user_id: user_id == ADMIN)
    assert await force_fail_task(row["id"], row["user_id"], 999, expected_provider_task_id=row["task_id"])
    assert await balance(priced_creator) == 100


@pytest.mark.asyncio
@pytest.mark.parametrize('model', ['wan_3', 'wan_3_prime'])
async def test_pg_creator_wan_one_reserve_and_accepted_retry_after_revocation(priced_creator, model):
    from bot.services.wan3_prime_lifecycle import Wan3PrimeActor, Wan3PrimeLifecycle
    from tests.test_wan3_prime_lifecycle import Probe, Provider, body

    pg = priced_creator
    user_id = (await pg.rows('SELECT id FROM users WHERE telegram_id = ?', (TARGET,)))[0]['id']
    actor = Wan3PrimeActor(user_id=user_id, telegram_id=TARGET)
    provider = Provider()
    prices = SimpleNamespace(get_video_quality_costs=lambda _: {'720p': 8})
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=prices, transport=provider)
    request = body(model=model)
    quote = await lifecycle.quote(actor, request)
    assert quote.reserve_credits == 7.5 and quote.rate_per_second == 1.5
    results = await asyncio.gather(*(lifecycle.launch(actor, request, quote, 'creator-pg-wan') for _ in range(3)))
    assert len({row['task_id'] for row in results}) == 1
    assert provider.creates == 1
    assert await balance(pg) == 92.5
    rows = await pg.rows('SELECT quote_json,reserve_credits FROM wan3_prime_intents WHERE user_id = ?', (user_id,))
    assert len(rows) == 1 and rows[0]['reserve_credits'] == 7.5
    assert json.loads(rows[0]['quote_json'])['rate_per_second'] == 1.5
    await membership.set_creator_tariff_membership(ADMIN, TARGET, False)
    repeated = await lifecycle.launch(actor, request, quote, 'creator-pg-wan')
    assert repeated['task_id'] == results[0]['task_id']
    assert provider.creates == 1 and await balance(pg) == 92.5


@pytest.mark.asyncio
async def test_pg_creator_wan_final_transaction_detects_membership_change(priced_creator, monkeypatch):
    from bot.services.wan3_prime_lifecycle import (
        Wan3PrimeActor,
        Wan3PrimeLifecycle,
        Wan3PrimeLifecycleError,
    )
    from tests.test_wan3_prime_lifecycle import Probe, Provider, body

    pg = priced_creator
    user_id = (await pg.rows('SELECT id FROM users WHERE telegram_id = ?', (TARGET,)))[0]['id']
    actor = Wan3PrimeActor(user_id=user_id, telegram_id=TARGET)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=SimpleNamespace(get_video_quality_costs=lambda _: {'720p': 8}), transport=provider)
    request = body(model='wan_3')
    quote = await lifecycle.quote(actor, request)
    original = lifecycle._recipe_and_quote

    async def revoke_after_quote(*args, **kwargs):
        prepared = await original(*args, **kwargs)
        await membership.set_creator_tariff_membership(ADMIN, TARGET, False)
        return prepared

    monkeypatch.setattr(lifecycle, '_recipe_and_quote', revoke_after_quote)
    with pytest.raises(Wan3PrimeLifecycleError) as caught:
        await lifecycle.launch(actor, request, quote, 'creator-pg-revoked')
    assert caught.value.code == 'stale_quote'
    assert provider.creates == 0 and await balance(pg) == 100
    assert await pg.rows('SELECT id FROM wan3_prime_intents WHERE user_id = ?', (user_id,)) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('change_before_start', [False, True])
async def test_pg_genjutsu_creator_pipeline_reserve_and_revision(priced_creator, change_before_start):
    from unittest.mock import AsyncMock

    from bot.genjutsu.contract import PipelineError
    from bot.genjutsu.pipeline import Pipeline
    from bot.genjutsu.repository import Repository

    pg = priced_creator
    preset_manager._price_config['creator_tariff']['genjutsu'] = {'prices': {'motion_transfer': {'720p': 3}}}
    repo = Repository(pg.connect)
    await repo.migrate()
    settings, version = await repo.settings()
    settings['public_enabled'] = True
    settings['verified_operations'] = ['motion_transfer']
    for operation in settings['prices']:
        settings['prices'][operation] = dict.fromkeys(settings['prices'][operation], 8)
    await repo.update_settings(ADMIN, version, settings)
    source = await repo.add_asset(TARGET, 'video', 'synthetic-source.mp4', {'duration_ms': 5000, 'size_bytes': 100, 'mime': 'video/mp4'})
    image = await repo.add_asset(TARGET, 'image', 'synthetic-image.png', {'size_bytes': 10, 'mime': 'image/png'})
    draft = {'source_asset_id': source['id'], 'steps': [{'operation': 'motion_transfer', 'resolution': '720p', 'prompt': '', 'preserve': '', 'references': [{'asset_id': image['id'], 'role': 'character', 'label': ''}], 'preset_id': None}], 'variants': 2, 'continuation': 'automatic'}
    project = await repo.save_project(TARGET, 'Synthetic creator test', draft)
    pipeline = Pipeline(repo, SimpleNamespace(), SimpleNamespace(ensure_asset=AsyncMock()))
    quote = await pipeline.quote(TARGET, project['id'], project['revision'])
    assert quote['total_credits'] == 60
    assert [item['credits_per_second'] for item in quote['allocations']] == [3, 3]
    if change_before_start:
        await membership.set_creator_tariff_membership(ADMIN, TARGET, False)
        with pytest.raises(PipelineError) as caught:
            await repo.start(TARGET, 'creator-genjutsu', quote['id'])
        assert caught.value.code == 'quote_changed'
        assert await balance(pg) == 100
        assert await pg.rows('SELECT id FROM genjutsu_runs WHERE owner = ?', (TARGET,)) == []
        return
    results = await asyncio.gather(*(repo.start(TARGET, 'creator-genjutsu', quote['id']) for _ in range(3)))
    assert len({row['id'] for row in results}) == 1
    assert await balance(pg) == 40
    stored = await pg.rows('SELECT rate,reserved_credits FROM genjutsu_steps WHERE run_id = ?', (results[0]['id'],))
    assert len(stored) == 2 and all(row['rate'] == 3 and row['reserved_credits'] == 30 for row in stored)
    await membership.set_creator_tariff_membership(ADMIN, TARGET, False)
    preset_manager._price_config['creator_tariff']['genjutsu']['prices']['motion_transfer']['720p'] = 99
    repeated = await repo.start(TARGET, 'creator-genjutsu', quote['id'])
    assert repeated['id'] == results[0]['id'] and await balance(pg) == 40
    assert len(await pg.rows("SELECT id FROM genjutsu_finance WHERE kind = 'reserve'")) == 1
