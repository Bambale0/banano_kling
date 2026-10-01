"""Refund invariants through the real PostgreSQL transaction adapter."""
import asyncio
import json
import os

import psycopg
import pytest

from bot import db as db_backend
from bot.services.task_watchdog import force_fail_task
from tests.runtime72_postgres_fixture import runtime_postgres_schema

pytestmark = pytest.mark.skipif(
    os.environ.get('RUNTIME_POSTGRES_TEST') != '1',
    reason='requires the dedicated ephemeral PostgreSQL runtime job',
)


@pytest.fixture(autouse=True)
async def refund_postgres_schema(isolated_database):
    assert db_backend.is_postgres()
    async with runtime_postgres_schema():
        yield


async def create_task(*, request_data=None):
    async with await psycopg.AsyncConnection.connect(os.environ['DATABASE_URL']) as connection:
        cursor = await connection.execute('''
            INSERT INTO users(telegram_id, credits) VALUES(741852, 100)
            ON CONFLICT(telegram_id) DO UPDATE SET credits = 100 RETURNING id
        ''')
        user_id = (await cursor.fetchone())[0]
        cursor = await connection.execute('''
            INSERT INTO generation_tasks(user_id, task_id, status, cost, request_data)
            VALUES(%s, 'current-provider-task', 'pending', 5, %s) RETURNING id
        ''', (user_id, json.dumps(request_data or {})))
        task_id = (await cursor.fetchone())[0]
        await connection.commit()
    return task_id, user_id


async def state(task_id, user_id):
    async with await psycopg.AsyncConnection.connect(os.environ['DATABASE_URL']) as connection:
        cursor = await connection.execute(
            'SELECT status, request_data, completed_at FROM generation_tasks WHERE id = %s',
            (task_id,),
        )
        task = await cursor.fetchone()
        cursor = await connection.execute('SELECT credits FROM users WHERE id = %s', (user_id,))
        credits = (await cursor.fetchone())[0]
    return task[0], json.loads(task[1]), task[2], credits


@pytest.mark.asyncio
async def test_concurrent_postgres_failures_refund_exactly_once():
    task_id, user_id = await create_task()
    results = await asyncio.gather(*[
        force_fail_task(task_id, user_id, 5, expected_provider_task_id='current-provider-task')
        for _ in range(4)
    ])
    assert results.count(True) == 1
    assert results.count(False) == 3
    status, data, completed_at, credits = await state(task_id, user_id)
    assert status == 'failed'
    assert completed_at is not None
    assert credits == 105
    assert data['refund_claimed'] is True
    assert data['refund_state'] == 'refunded'


@pytest.mark.asyncio
async def test_stale_provider_id_cannot_fail_or_refund_replacement():
    task_id, user_id = await create_task()
    assert await force_fail_task(
        task_id, user_id, 5, expected_provider_task_id='previous-provider-task',
    ) is False
    assert await state(task_id, user_id) == ('pending', {}, None, 100)


@pytest.mark.asyncio
async def test_credit_failure_rolls_back_status_and_refund_marker():
    task_id, user_id = await create_task()
    with pytest.raises(RuntimeError, match='Refund user missing'):
        await force_fail_task(
            task_id, -1, 5, expected_provider_task_id='current-provider-task',
        )
    assert await state(task_id, user_id) == ('pending', {}, None, 100)
    assert await force_fail_task(
        task_id, user_id, 5, expected_provider_task_id='current-provider-task',
    ) is True
    assert (await state(task_id, user_id))[3] == 105


@pytest.mark.asyncio
async def test_preexisting_refund_marker_prevents_watchdog_double_credit():
    task_id, user_id = await create_task(request_data={'refund_claimed': True, 'refund_state': 'refunded'})
    assert await force_fail_task(
        task_id, user_id, 5, expected_provider_task_id='current-provider-task',
    ) is True
    status, data, _, credits = await state(task_id, user_id)
    assert status == 'failed'
    assert data['refund_state'] == 'refunded'
    assert credits == 100
