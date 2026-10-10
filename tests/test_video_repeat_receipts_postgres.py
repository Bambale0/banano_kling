"""Typed repeat launch serialization through the ephemeral production PG adapter."""
import asyncio
import hashlib
import json
import os
import uuid

import psycopg
import pytest

from bot import database
from tests.test_result_durability_postgres import (
    delivery_postgres_schema as delivery_postgres_schema,  # noqa: PLC0414 - pytest fixture re-export
)
from tests.test_video_repeat_private_contract import (
    typed_video_entrypoint as typed_video_entrypoint,  # noqa: PLC0414 - pytest fixture re-export
)
from tests.test_video_repeat_receipts import configure_actual_entry, reserve

pytestmark = pytest.mark.skipif(
    os.environ.get('RUNTIME_POSTGRES_TEST') != '1',
    reason='requires the dedicated ephemeral PostgreSQL runtime job',
)


@pytest.fixture(autouse=True)
async def receipt_postgres_schema(delivery_postgres_schema):
    # The existing guarded fixture accepts only the local banano_runtime_test DB.
    async with await psycopg.AsyncConnection.connect(os.environ['DATABASE_URL']) as conn:
        for name, definition in (
            ('source_feed_gen_id', 'BIGINT'), ('parent_generation_id', 'BIGINT'),
            ('action_type', 'TEXT'),
        ):
            await conn.execute(f'ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS {name} {definition}')
        await conn.commit()
    yield


@pytest.mark.asyncio
@pytest.mark.parametrize('model', ['seedance_2', 'seedance_2_5'])
async def test_pg_simultaneous_authenticated_repeat_has_one_debit_and_provider(monkeypatch, typed_video_entrypoint, model, tmp_path):
    from bot import db as db_backend
    from bot.creator_tariff import VideoQuote
    from bot.services import seedance_quote_lifecycle as lifecycle
    from bot.services import wan3_prime_storage as storage

    entry = typed_video_entrypoint
    viewer, debit, refund, provider, original_request = await configure_actual_entry(monkeypatch, entry, model)
    monkeypatch.setattr(storage, "UPLOAD_ROOT", tmp_path)

    async def fixture_snapshots(actor, sources):
        # Only acquisition/probing is stubbed. Actual owned rows, hash checks,
        # quote claim, SQL debit, canonical binding and replay remain real.
        rows = []
        batch = uuid.uuid4().hex
        async with db_backend.connect(database.DATABASE_PATH) as db:
            for index, _source in enumerate(sources):
                path = tmp_path / f"owned-{batch}-{actor.user_id}-{index}.mp4"
                path.write_bytes(f"synthetic immutable video {index}".encode())
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                url = f"https://example.test/pinned/{batch}/{actor.user_id}/{index}.mp4"
                cursor = await db.execute(
                    "INSERT INTO wan3_prime_media(user_id,telegram_id,kind,public_url,local_path,filename,size_bytes,sha256,media_info,source) "
                    "VALUES (?,?,'video',?,?,?, ?,?,'{}','seedance_quote_snapshot') RETURNING id",
                    (actor.user_id,actor.telegram_id,url,str(path),path.name,path.stat().st_size,digest))
                media_id = (await cursor.fetchone())[0]
                rows.append({"media_id":media_id,"url":url,"seconds":3.5,"sha256":digest})
            await db.commit()
        return rows

    async def fixture_quote(telegram_id, selected_model, duration=5, quality=None, **kwargs):
        inputs = kwargs["input_video_seconds"]
        output = kwargs["selected_output_seconds"]
        cost = round((inputs + output) * 2)
        return VideoQuote(model=selected_model,duration=duration,quality=quality,cost=cost,charge_cost=cost,
            profile="standard",base_cost=cost,reference_multiplier=1,revision="synthetic-rate-v2",version=2,
            billing_mode="input_plus_selected_output",input_seconds=inputs,selected_output_seconds=output,
            billable_seconds=inputs+output,rate=2,references_fingerprint=kwargs["references_fingerprint"])

    monkeypatch.setattr(lifecycle,"prepare_video_snapshots",fixture_snapshots)
    monkeypatch.setattr(lifecycle,"quote_video_for_actor",fixture_quote)
    def request(**fields):
        result = original_request()
        result._read_bytes = json.dumps({**json.loads(result._read_bytes),**fields}).encode()
        return result

    preview = await entry.call(request(video_quote_only=True,seedance25_quote_only=True))
    assert preview.status == 200, preview.text
    quote = json.loads(preview.text)
    assert quote["input_seconds"] == 7
    assert quote["selected_output_seconds"] == 5
    assert quote["charge_cost"] == 24
    provider.assert_not_awaited()
    assert (await database.get_or_create_user(viewer.telegram_id)).credits == 100
    async with db_backend.connect(database.DATABASE_PATH) as db:
        assert (await (await db.execute("SELECT COUNT(*) FROM generation_tasks WHERE task_id LIKE 'video_repeat_receipt_%'")).fetchone())[0] == 0

    fields = {"video_quote_id":quote["quote_id"],"video_quote_hash":quote["quote_hash"]}
    responses = await asyncio.gather(*(entry.call(request(**fields)) for _ in range(4)))
    assert any(response.status == 200 for response in responses), [response.text for response in responses]
    for response in responses:
        body = json.loads(response.text)
        assert response.status in {200,409}, body
        if response.status == 200:
            assert body["task_id"] == "synthetic-receipt-provider"
        else:
            assert body["code"] == "video_status_pending"
    provider.assert_awaited_once()
    refund.assert_not_awaited()
    debit.assert_not_awaited()  # New owner is the atomic receipt SQL transaction.
    assert (await database.get_or_create_user(viewer.telegram_id)).credits == 100 - quote["charge_cost"]
    store = await lifecycle.receipt_store()
    receipt = await store.find(viewer.telegram_id,quote["quote_id"])
    assert receipt["phase"] == "accepted" and receipt["charged_cost"] == quote["charge_cost"]
    task = await database.get_task_by_id("synthetic-receipt-provider")
    assert task.status == "pending" and task.cost == quote["charge_cost"]
    assert json.loads(task.request_data)["seedance_quote_id"] == quote["quote_id"]
    await database.complete_video_task(task.task_id,"https://example.test/result.mp4")
    replay = await entry.call(request(**fields))
    assert replay.status == 200 and json.loads(replay.text)["status"] == "done"
    provider.assert_awaited_once()
    assert (await database.get_or_create_user(viewer.telegram_id)).credits == 100 - quote["charge_cost"]


@pytest.mark.asyncio
async def test_pg_stale_reserved_reclaim_and_original_phase_advance_are_mutually_exclusive():
    from bot import db as db_backend
    user = await database.get_or_create_user(882060)
    for source in range(100, 106):
        original = await reserve(user, source)
        async with db_backend.connect(database.DATABASE_PATH) as db:
            await db.execute("UPDATE generation_tasks SET created_at = '2000-01-01', updated_at = NULL WHERE task_id = ?", (original['task_id'],))
            await db.commit()
        advanced, replacement = await asyncio.gather(
            database.finish_private_video_repeat(original['task_id'], user.id, phase='debit_pending', attempted_cost=2),
            reserve(user, source),
        )
        assert bool(advanced) != bool(replacement['created'])
        if replacement['created']:
            assert replacement['task_id'] != original['task_id']
            assert not await database.finish_private_video_repeat(original['task_id'], user.id, phase='debit_pending', attempted_cost=2)
        else:
            assert replacement['task_id'] == original['task_id']


@pytest.mark.asyncio
async def test_pg_concurrent_stale_reclaim_creates_one_replacement():
    from bot import db as db_backend
    user = await database.get_or_create_user(882061)
    original = await reserve(user)
    async with db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE generation_tasks SET created_at = '2000-01-01', updated_at = NULL WHERE task_id = ?", (original['task_id'],))
        await db.commit()
    receipts = await asyncio.gather(*(reserve(user) for _ in range(4)))
    assert sum(item['created'] for item in receipts) == 1
    assert len({item['task_id'] for item in receipts}) == 1
    assert receipts[0]['task_id'] != original['task_id']
