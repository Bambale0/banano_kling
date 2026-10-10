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
from tests.test_wan3_prime_lifecycle import (
    Downloader,
    Prices,
    Probe,
    Provider,
    balance,
    body,
    user_actor,
)

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
                ("source_feed_gen_id", "BIGINT"), ("parent_generation_id", "BIGINT"), ("action_type", "TEXT"),
                ("is_public_feed", "BOOLEAN DEFAULT FALSE"), ("is_profile_visible", "BOOLEAN DEFAULT FALSE"),
            ):
                await conn.execute(psycopg.sql.SQL("ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS {} " + definition).format(psycopg.sql.Identifier(name)))
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_chat_state TEXT DEFAULT 'unknown'")
            for name, definition in (
                ("author_id", "BIGINT"), ("title", "TEXT"), ("description", "TEXT"),
                ("category", "TEXT"), ("prompt_text", "TEXT"), ("model", "TEXT"),
                ("tags", "TEXT"), ("is_public", "BOOLEAN DEFAULT FALSE"),
                ("source_generation_id", "BIGINT"), ("uses_count", "INTEGER DEFAULT 0"),
                ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"), ("updated_at", "TIMESTAMP"),
            ):
                await conn.execute(psycopg.sql.SQL("ALTER TABLE user_prompts ADD COLUMN IF NOT EXISTS {} " + definition).format(psycopg.sql.Identifier(name)))
            await conn.execute("CREATE TABLE IF NOT EXISTS bot_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_by_telegram_id BIGINT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            await conn.execute("""CREATE TABLE IF NOT EXISTS prompt_repeat_events (
                id BIGSERIAL PRIMARY KEY, author_id BIGINT NOT NULL, repeater_id BIGINT NOT NULL,
                source_type TEXT NOT NULL, source_id BIGINT NOT NULL, repeat_task_id TEXT UNIQUE,
                credits_spent DOUBLE PRECISION DEFAULT 0, amount_rub DOUBLE PRECISION NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
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


@pytest.mark.asyncio
async def test_postgres_curated_edit_keeps_roles_and_settles_reward_once():
    from bot import database
    from bot.services.wan3_prime_lifecycle import Wan3PrimeActor
    from bot.services.wan3_prime_repeat import public_plan
    from bot.services.wan3_prime_trends import get_trend_plan, publish_trend

    owner = await user_actor(100, telegram_id=991284004)
    admin = Wan3PrimeActor(owner.user_id, owner.telegram_id, is_admin=True)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(file_duration=5), preset_manager=Prices(), transport=provider,
        downloader=Downloader(Path('static/uploads/wan3_prime/results/pg-trend.mp4')))
    recipe = body(scenario='edit', prompt='Replace Video1 appearance using Image1', seed=0, audio=False,
        reference_image_urls=['https://owned.test/author.png'], reference_video_urls=['https://owned.test/source.mp4'],
        reference_audio_urls=['https://owned.test/voice.mp3'], reference_file_urls=['https://owned.test/script.txt'])
    quote = await lifecycle.quote(admin, recipe)
    source = await lifecycle.launch(admin, recipe, quote, 'pg-trend-source')
    async with db_backend.connect() as db:
        await db.execute("UPDATE generation_tasks SET status = 'completed', result_url = ? WHERE task_id = ?",
                         ('https://owned.test/preview.mp4', source['task_id']))
        await db.commit()
    trend = await publish_trend(admin, task_id=source['task_id'], title='PG full editor', description='Replace subject', replacement_keys=['image:0'])
    viewer = await user_actor(100, telegram_id=991284005)
    plan = public_plan(await get_trend_plan(viewer, trend['trend_id']))
    assert 'source.mp4' not in str(plan)
    request = {**plan['recipe'], 'trend_id': trend['trend_id'], 'repeat_plan_hash': plan['repeat_plan_hash'],
               'repeat_replacements': {'image:0': 'https://owned.test/viewer.png'}}
    provider.create_result = {'success': True, 'task_id': 'provider_repeat'}
    quote = await lifecycle.quote(viewer, request)
    result = await lifecycle.launch(viewer, request, quote, 'pg-trend-repeat')
    assert provider.recipe.reference_video_urls == ['https://owned.test/source.mp4']
    assert provider.recipe.seed == 0 and provider.recipe.audio is False
    provider.statuses['provider_repeat'] = {'taskId': 'provider_repeat', 'state': 'success', 'resultUrls': ['https://owned.test/result.mp4']}
    await asyncio.gather(*(lifecycle.reconcile_once(provider_task_id='provider_repeat') for _ in range(3)))
    assert await balance(viewer.user_id) == 80
    async with db_backend.connect() as db:
        events = await (await db.execute('SELECT COUNT(*) FROM prompt_repeat_events WHERE source_type = ? AND source_id = ?', ('prompt', trend['trend_id']))).fetchone()
        runs = await (await db.execute('SELECT COUNT(*) FROM trend_generation_runs WHERE trend_id = ?', (trend['trend_id'],))).fetchone()
    assert events[0] == 1 and runs[0] == 1
    assert (await database.get_task_by_id(result['task_id'])).status == 'completed'


@pytest.mark.asyncio
async def test_postgres_storage_quota_is_atomic_across_completed_and_concurrent_uploads(monkeypatch):
    from bot.services.wan3_prime_media import Wan3PrimeValidationError
    from bot.services.wan3_prime_storage import wan3_prime_storage
    from tests.test_wan3_prime_storage import png_bytes

    actor = await user_actor(100, telegram_id=991284006)
    image = png_bytes()
    monkeypatch.setenv('WAN3_UPLOAD_USER_QUOTA_BYTES', str(len(image) * 2))
    sessions = await asyncio.gather(*(wan3_prime_storage.init_upload(actor, kind='image', filename='quota.png', size=len(image))
                                      for _ in range(6)), return_exceptions=True)
    admitted = [item for item in sessions if isinstance(item, dict)]
    assert len(admitted) == 2
    assert all(isinstance(item, (dict, Wan3PrimeValidationError)) for item in sessions)
    first = admitted[0]['upload_id']
    await wan3_prime_storage.save_chunk(actor, upload_id=first, index=0, total=1, chunk=image)
    await wan3_prime_storage.complete_upload(actor, upload_id=first)
    with pytest.raises(Wan3PrimeValidationError) as error:
        await wan3_prime_storage.init_upload(actor, kind='image', filename='over.png', size=len(image))
    assert error.value.status == 429


@pytest.mark.asyncio
async def test_postgres_result_retention_keeps_accounting(tmp_path, monkeypatch):
    from bot import database
    from bot.services.wan3_prime_storage import wan3_prime_storage

    monkeypatch.setenv('WAN3_RESULT_RETENTION_SECONDS', '1')
    actor = await user_actor(100, telegram_id=991284007)
    provider = Provider()
    path = Path('static/uploads/wan3_prime/results/pg-expiry.mp4')
    lifecycle = Wan3PrimeLifecycle(probe=Probe(file_duration=5), preset_manager=Prices(), transport=provider, downloader=Downloader(path))
    quote = await lifecycle.quote(actor, body())
    created = await lifecycle.launch(actor, body(), quote, 'pg-result-expiry')
    provider.statuses['provider_1'] = {'taskId': 'provider_1', 'state': 'success', 'resultUrls': ['https://owned.test/pg-result.mp4']}
    await lifecycle.reconcile_once(provider_task_id='provider_1')
    async with db_backend.connect() as db:
        await db.execute("UPDATE generation_tasks SET completed_at = '2000-01-01' WHERE task_id = ?", (created['task_id'],))
        await db.execute("UPDATE wan3_prime_intents SET delivery_status = 'delivered' WHERE internal_task_id = ?", (created['task_id'],))
        await db.commit()
    await wan3_prime_storage.cleanup_expired()
    assert not path.exists()
    assert await balance(actor.user_id) == 90
    assert (await database.get_task_by_id(created['task_id'])).status == 'completed'
