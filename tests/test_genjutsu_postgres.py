"""Genjutsu schema and financial invariants through the real PostgreSQL adapter."""
import asyncio
import os
from uuid import uuid4

import psycopg
import pytest

from bot import db as db_backend
from bot.genjutsu.contract import compile_plan, quote_plan
from bot.genjutsu.recipes import RecipeStore
from bot.genjutsu.repository import Repository
from tests.runtime72_postgres_fixture import runtime_postgres_schema

pytestmark = pytest.mark.skipif(
    os.environ.get("RUNTIME_POSTGRES_TEST") != "1",
    reason="requires the dedicated ephemeral PostgreSQL runtime job",
)


@pytest.fixture(autouse=True)
async def genjutsu_postgres_schema(isolated_database):
    assert db_backend.is_postgres()
    async with runtime_postgres_schema():
        yield


@pytest.mark.asyncio
async def test_postgres_migration_and_concurrent_refund_are_idempotent(monkeypatch):
    owner = 93939393
    repo = Repository(db_backend.connect)
    await repo.migrate()
    await repo.migrate()
    recipes = RecipeStore(repo)
    await recipes.migrate()
    await recipes.migrate()

    async with await psycopg.AsyncConnection.connect(os.environ["DATABASE_URL"]) as connection:
        columns = await connection.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='genjutsu_recipes'"
        )
        recipe_columns = {row[0] async for row in columns}
        assert "verification_run_id" in recipe_columns
        assert "source_binding" in recipe_columns
        await connection.execute(
            "INSERT INTO users(telegram_id, credits) VALUES(%s, 100) "
            "ON CONFLICT(telegram_id) DO UPDATE SET credits=100",
            (owner,),
        )
        await connection.commit()

    settings, version = await repo.settings()
    settings["public_enabled"] = True
    settings["verified_operations"] = ["motion_transfer"]
    settings["prices"]["motion_transfer"] = {"480p": 1, "720p": 1, "1080p": 1}
    await repo.update_settings(1, version, settings)

    source = await repo.add_asset(owner, "video", f"pg-source-{uuid4().hex}.mp4", {
        "duration_ms": 5_000, "size_bytes": 100, "mime": "video/mp4",
    })
    reference = await repo.add_asset(owner, "image", f"pg-reference-{uuid4().hex}.png", {
        "size_bytes": 10, "mime": "image/png",
    })
    draft = {
        "source_asset_id": source["id"],
        "steps": [{
            "operation": "motion_transfer", "resolution": "720p", "prompt": "",
            "preserve": "", "references": [{
                "asset_id": reference["id"], "role": "character", "label": "",
            }], "preset_id": None,
        }],
        "variants": 1,
        "continuation": "automatic",
    }
    project = await repo.save_project(owner, "PostgreSQL", draft)
    settings, version = await repo.settings()
    assets = await repo.get_assets(owner, {source["id"], reference["id"]})
    plan = compile_plan(draft, assets, settings)
    quote = await repo.create_quote(
        owner, project["id"], project["revision"], plan,
        quote_plan(plan, assets, settings), version, settings,
    )
    request_key = "postgres-" + uuid4().hex
    left, right = await asyncio.gather(
        repo.start(owner, request_key, quote["id"]),
        repo.start(owner, request_key, quote["id"]),
    )
    assert left["id"] == right["id"]
    step = await repo.claim_step(settings)
    await repo.finish_step(step["id"], step["lease_token"], "failed", error_code="test")
    assert await repo.balance(owner) == 100

    # New terminal notification is committed with the refund and claimed once
    # through the real PostgreSQL adapter under competing workers.
    notices = await asyncio.gather(repo.claim_notification(settings), repo.claim_notification(settings))
    notices = [item for item in notices if item is not None]
    assert len(notices) == 1
    notice = notices[0]
    assert notice['run_id'] == left['id']
    assert notice['summary']['reserved_credits'] == 5
    assert notice['summary']['refunded_credits'] == 5
    assert notice['summary']['charged_credits'] == 0
    await repo.finish_notification(left['id'], notice['lease_token'], 'delivered', message_id='synthetic')
    await repo.migrate()
    await repo.cancel(owner, left['id'])
    assert await repo.claim_notification(settings) is None


    # A failure after the outbox insert must roll back the refund, terminal
    # state and notice together through the actual PostgreSQL transaction.
    next_quote = await repo.create_quote(
        owner, project['id'], project['revision'], plan,
        quote_plan(plan, assets, settings), version, settings,
    )
    next_run = await repo.start(owner, 'pg-atomic-' + uuid4().hex, next_quote['id'])
    next_step = await repo.claim_step(settings)
    enqueue = repo._enqueue_terminal_notification

    async def fail_after_enqueue(db, run_id, state):
        await enqueue(db, run_id, state)
        raise RuntimeError('synthetic outbox transaction interruption')

    monkeypatch.setattr(repo, '_enqueue_terminal_notification', fail_after_enqueue)
    with pytest.raises(RuntimeError, match='synthetic outbox transaction interruption'):
        await repo.finish_step(next_step['id'], next_step['lease_token'], 'failed', error_code='test')
    assert await repo.balance(owner) == 95
    assert (await repo.get_run(owner, next_run['id']))['state'] == 'running'
    assert await repo.claim_notification(settings) is None
    monkeypatch.setattr(repo, '_enqueue_terminal_notification', enqueue)
    await repo.finish_step(next_step['id'], next_step['lease_token'], 'failed', error_code='test')
    assert await repo.balance(owner) == 100
    notice = await repo.claim_notification(settings)
    assert notice['run_id'] == next_run['id']
    assert notice['summary']['refunded_credits'] == 5
    assert await repo.claim_notification(settings) is None
