"""Real PostgreSQL contract on the explicitly disposable runtime CI database."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio

from bot import db as db_backend
from bot.services.wan3_prime_lifecycle import Wan3PrimeLifecycle
from tests.runtime72_postgres_fixture import runtime_postgres_schema
from tests.test_wan3_prime_lifecycle import Downloader, Prices, Probe, Provider, balance, body, user_actor

pytestmark = pytest.mark.skipif(os.getenv("RUNTIME_POSTGRES_TEST") != "1", reason="isolated PostgreSQL CI only")


@pytest_asyncio.fixture(autouse=True)
async def wan_postgres_schema(tmp_path, monkeypatch):
    async with runtime_postgres_schema():
        # runtime_postgres_schema asserts a loopback host and the exact dedicated
        # database name before any DDL/TRUNCATE. Never point this at production.
        assert db_backend.is_postgres()
        async with await psycopg.AsyncConnection.connect(os.environ["DATABASE_URL"]) as conn:
            for name, definition in (
                ("telegram_id", "BIGINT"), ("type", "TEXT"), ("preset_id", "TEXT"),
                ("model", "TEXT"), ("duration", "INTEGER"), ("aspect_ratio", "TEXT"),
                ("prompt", "TEXT"), ("result_url", "TEXT"), ("result_urls", "TEXT"),
            ):
                await conn.execute(psycopg.sql.SQL("ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS {} " + definition).format(psycopg.sql.Identifier(name)))
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_chat_state TEXT DEFAULT 'unknown'")
            await conn.commit()
        monkeypatch.chdir(tmp_path)
        lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=Provider())
        await lifecycle.init_schema()
        async with await psycopg.AsyncConnection.connect(os.environ["DATABASE_URL"]) as conn:
            await conn.execute("TRUNCATE wan3_prime_intents, wan3_prime_media, wan3_prime_upload_sessions")
            await conn.commit()
        yield


@pytest.mark.asyncio
async def test_native_schema_and_concurrent_idempotent_reservation_and_refund():
    actor = await user_actor(100, telegram_id=991284001)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=provider)
    await asyncio.gather(lifecycle.init_schema(), lifecycle.init_schema())
    quote = await lifecycle.quote(actor, body())
    results = await asyncio.gather(*(lifecycle.launch(actor, body(), quote, "same-key") for _ in range(8)))
    assert len({item["task_id"] for item in results}) == 1
    assert provider.creates == 1
    assert await balance(actor.user_id) == 90
    task_id = results[0]["task_id"]
    await asyncio.gather(*(lifecycle._terminal_failure(task_id, "provider_error", "synthetic rejection") for _ in range(8)))
    assert await balance(actor.user_id) == 100
    record = await lifecycle.status(actor, task_id)
    assert record["status"] == "failed"
    assert record["refunded_credits"] == 10


@pytest.mark.asyncio
async def test_auto_settlement_duplicate_callback_and_late_failure_do_not_mutate_twice():
    actor = await user_actor(100, telegram_id=991284002)
    provider = Provider()
    path = Path("static/uploads/wan3_prime/results/postgres-result.mp4")
    lifecycle = Wan3PrimeLifecycle(probe=Probe(file_duration=5.25), preset_manager=Prices(),
                                  transport=provider, downloader=Downloader(path))
    quote = await lifecycle.quote(actor, body(duration=-1))
    accepted = await lifecycle.launch(actor, body(duration=-1), quote, "auto-key")
    assert await balance(actor.user_id) == 40
    provider.statuses["provider_1"] = {"taskId": "provider_1", "model": "wan/3-0-video-prime", "state": "success",
                                       "resultJson": '{"resultUrls":["https://provider.test/result.mp4"]}'}
    await asyncio.gather(*(lifecycle.reconcile_once(provider_task_id="provider_1") for _ in range(5)))
    assert await balance(actor.user_id) == 89.5
    await lifecycle._terminal_failure(accepted["task_id"], "late_failure", "ignored")
    assert await balance(actor.user_id) == 89.5
    status = await lifecycle.status(actor, accepted["task_id"])
    assert status["status"] == "completed"
    assert status["charged_credits"] == 10.5


@pytest.mark.asyncio
async def test_chunked_storage_runs_through_real_postgres_adapter():
    from bot.services.wan3_prime_storage import wan3_prime_storage
    from tests.test_wan3_prime_storage import png_bytes

    actor = await user_actor(100, telegram_id=991284003)
    image = png_bytes()
    session = await wan3_prime_storage.init_upload(actor, kind="image", filename="fixture.png", size=len(image))
    await asyncio.gather(*(wan3_prime_storage.save_chunk(actor, upload_id=session["upload_id"], index=0, total=1, chunk=image) for _ in range(3)))
    saved = await wan3_prime_storage.complete_upload(actor, upload_id=session["upload_id"])
    replay = await wan3_prime_storage.complete_upload(actor, upload_id=session["upload_id"])
    assert saved == replay
    assert saved["kind"] == "image"
