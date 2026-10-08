"""Typed repeat launch serialization through the ephemeral production PG adapter."""
import asyncio
import os

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
async def test_pg_simultaneous_authenticated_repeat_has_one_debit_and_provider(monkeypatch, typed_video_entrypoint, model):
    entry = typed_video_entrypoint
    viewer, debit, refund, provider, request = await configure_actual_entry(monkeypatch, entry, model)
    responses = await asyncio.gather(*(entry.call(request()) for _ in range(4)))
    assert sorted(response.status for response in responses) == [200, 409, 409, 409]
    debit.assert_awaited_once_with(viewer.telegram_id, 2)
    provider.assert_awaited_once()
    refund.assert_not_awaited()
    assert (await database.get_or_create_user(viewer.telegram_id)).credits == 98
    task = await database.get_task_by_id('synthetic-receipt-provider')
    assert task.status == 'pending'
    assert not (await reserve(viewer))['created']
    assert (await reserve(viewer, 43))['created']
    other = await database.get_or_create_user(882103)
    assert (await reserve(other))['created']
    await database.complete_video_task(task.task_id, None)
    assert (await reserve(viewer))['created']
