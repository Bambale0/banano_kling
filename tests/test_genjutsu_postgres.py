"""Genjutsu schema and financial invariants through the real PostgreSQL adapter."""
import asyncio
import os
from contextlib import asynccontextmanager
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

@pytest.mark.asyncio
async def test_postgres_feed_publication_and_withdrawal_admission_are_transactional(monkeypatch):
    """Exercise real SQL locks, bool translation, atomic adapter writes and rollback."""
    from unittest.mock import AsyncMock

    from bot import database
    from bot.genjutsu.contract import PipelineError
    from bot.genjutsu.feed import FeedPublisher

    owner = 94949494
    async with await psycopg.AsyncConnection.connect(os.environ["DATABASE_URL"]) as connection:
        for name, definition in (
            ("telegram_id", "BIGINT"), ("type", "TEXT"), ("preset_id", "TEXT"), ("model", "TEXT"),
            ("duration", "INTEGER"), ("prompt", "TEXT"), ("result_url", "TEXT"), ("result_urls", "TEXT"),
            ("is_profile_visible", "BOOLEAN DEFAULT FALSE"), ("is_adult_content", "BOOLEAN DEFAULT FALSE"),
            ("feed_prompt_visible", "BOOLEAN DEFAULT FALSE"), ("feed_references_visible", "BOOLEAN DEFAULT FALSE"),
            ("feed_reference_selection", "TEXT"), ("feed_repeat_reference_selection", "TEXT"),
            ("feed_published_at", "TIMESTAMP"),
        ):
            await connection.execute(f"ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS {name} {definition}")
        await connection.execute("INSERT INTO users(telegram_id,credits) VALUES(%s,1000) ON CONFLICT(telegram_id) DO UPDATE SET credits=1000", (owner,))
        await connection.commit()
    repo = Repository(db_backend.connect)
    await repo.migrate()
    recipes = RecipeStore(repo)
    await recipes.migrate()
    await recipes.migrate()
    repo.start_validator = recipes.validate_start
    settings, version = await repo.settings()
    settings["public_enabled"] = True
    settings["verified_operations"] = ["motion_transfer"]
    settings["prices"]["motion_transfer"] = {"480p": 1, "720p": 1, "1080p": 1}
    await repo.update_settings(1, version, settings)
    source = await repo.add_asset(owner, "video", uuid4().hex + ".mp4", {"duration_ms": 5000, "size_bytes": 10})
    image = await repo.add_asset(owner, "image", uuid4().hex + ".png", {"size_bytes": 10})
    output = await repo.add_asset(owner, "video", uuid4().hex + ".mp4", {"duration_ms": 5000, "size_bytes": 10})
    draft = {"source_asset_id": source["id"], "variants": 1, "continuation": "automatic", "steps": [{
        "operation": "motion_transfer", "resolution": "720p", "prompt": "private", "preserve": "", "preset_id": None,
        "references": [{"asset_id": image["id"], "role": "character", "label": "Photo", "binding": "user"}],
    }]}
    project = await repo.save_project(owner, "PG Feed", draft)
    settings, version = await repo.settings()
    assets = await repo.get_assets(owner, {source["id"], image["id"]})
    plan = compile_plan(draft, assets, settings)
    quote = await repo.create_quote(owner, project["id"], 1, plan, quote_plan(plan, assets, settings), version, settings)
    accepted = await repo.start(owner, "pg-feed-" + uuid4().hex, quote["id"])
    run = await repo.get_run(owner, accepted["id"])
    step = run["steps"][0]
    async with repo.transaction() as db:
        await db.execute("UPDATE genjutsu_runs SET state='completed' WHERE id=?", (run["id"],))
        await db.execute("UPDATE genjutsu_steps SET status='completed',output_asset_id=?,actual_credits=5 WHERE id=?", (output["id"], step["id"]))
    monkeypatch.setattr(database, "get_feed_generation_card", AsyncMock(return_value={"id": 1}))
    publisher = FeedPublisher(repo, recipes, AsyncMock(return_value="https://fixture.test/output.mp4"))
    left, right = await asyncio.gather(
        publisher.publish(owner, run["id"], step["id"], "PG public", "user"),
        publisher.publish(owner, run["id"], step["id"], "PG public", "user"),
    )
    assert left["recipe"]["id"] == right["recipe"]["id"]
    async with repo.connect() as db:
        row = await (await db.execute("SELECT COUNT(*) AS n FROM generation_tasks WHERE task_id=?", ("genjutsu-feed-" + step["id"],))).fetchone()
        assert row["n"] == 1
    instance = await recipes.instantiate(owner, left["recipe"]["id"], [image["id"]], {}, source_asset_id=source["id"])
    hidden = await repo.get_project(owner, instance["id"])
    repeat_quote = await repo.create_quote(owner, instance["id"], 1, hidden["plan"], quote_plan(hidden["plan"], assets, settings), version, settings, private_recipe=True)
    async with repo.connect() as db:
        await db.execute("UPDATE generation_tasks SET is_public_feed=0,is_profile_visible=0 WHERE task_id=?", ("genjutsu-feed-" + step["id"],))
        await db.commit()
    balance = await repo.balance(owner)
    with pytest.raises(PipelineError, match="recipe_unavailable"):
        await repo.start(owner, "pg-withdraw-" + uuid4().hex, repeat_quote["id"])
    assert await repo.balance(owner) == balance


    # Hold the ordinary publication row while the stale retry starts. Without
    # the task-row lock, its SELECT reads the old visible version; our commit
    # then lands before its final UPDATE and the stale retry resurrects Feed.
    # With the lock, the retry waits, sees the withdrawal and fails closed.
    original_connect = repo.connect
    task_id = "genjutsu-feed-" + step["id"]
    for keep_profile in (False, True):
        reached_guard = asyncio.Event()
        release_read = asyncio.Event()

        class ObservedConnection:
            def __init__(self, connection, reached=reached_guard, release=release_read):
                self.connection = connection
                self.reached_guard = reached
                self.release_read = release

            def __getattr__(self, name):
                return getattr(self.connection, name)

            async def execute(self, sql, parameters=()):
                if sql.startswith("UPDATE generation_tasks SET updated_at=updated_at"):
                    self.reached_guard.set()
                cursor = await self.connection.execute(sql, parameters)
                if sql.startswith("SELECT is_public_feed,is_adult_content FROM generation_tasks"):
                    self.reached_guard.set()
                    await self.release_read.wait()
                return cursor

        @asynccontextmanager
        async def observed_connect():
            async with original_connect() as connection:
                yield ObservedConnection(connection)

        repo.connect = observed_connect
        pending = None
        try:
            async with await psycopg.AsyncConnection.connect(os.environ["DATABASE_URL"]) as withdrawal:
                await withdrawal.execute(
                    "UPDATE generation_tasks SET is_public_feed=TRUE,is_profile_visible=TRUE WHERE task_id=%s",
                    (task_id,),
                )
                await withdrawal.commit()
                await withdrawal.execute(
                    "UPDATE generation_tasks SET is_public_feed=FALSE,is_profile_visible=%s WHERE task_id=%s",
                    (keep_profile, task_id),
                )
                pending = asyncio.create_task(
                    publisher.publish(owner, run["id"], step["id"], "PG public", "user")
                )
                await asyncio.wait_for(reached_guard.wait(), timeout=10)
                await withdrawal.commit()
                release_read.set()
                with pytest.raises(PipelineError, match="feed_publication_withdrawn"):
                    await asyncio.wait_for(pending, timeout=10)
                current = await (await withdrawal.execute(
                    "SELECT is_public_feed,is_profile_visible FROM generation_tasks WHERE task_id=%s",
                    (task_id,),
                )).fetchone()
                assert current == (False, keep_profile)
        finally:
            release_read.set()
            if pending is not None and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            repo.connect = original_connect
    assert await repo.balance(owner) == balance
