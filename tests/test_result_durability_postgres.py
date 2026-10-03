"""Result completion, delivery leases and refunds on the real PG adapter."""

import asyncio
import json
import os

import psycopg
import pytest

from bot import database
from bot import db as db_backend
from bot.services.task_watchdog import force_fail_task, get_stuck_tasks
from tests.runtime72_postgres_fixture import runtime_postgres_schema

pytestmark = pytest.mark.skipif(
    os.environ.get("RUNTIME_POSTGRES_TEST") != "1",
    reason="requires the dedicated ephemeral PostgreSQL runtime job",
)


@pytest.fixture(autouse=True)
async def delivery_postgres_schema(isolated_database, monkeypatch):
    from bot import postgres_aiosqlite, postgres_pool

    assert db_backend.is_postgres()
    # pytest uses a fresh event loop per test; production owns a single loop.
    monkeypatch.setattr(postgres_pool, "_POOL_LOCK", None)
    monkeypatch.setattr(postgres_pool, "_PERFORMANCE_INDEXES_LOCK", None)
    monkeypatch.setattr(postgres_aiosqlite, "_HELPERS_LOCK", None)
    async with runtime_postgres_schema():
        async with await psycopg.AsyncConnection.connect(
            os.environ["DATABASE_URL"]
        ) as conn:
            for name, definition in (
                ("type", "TEXT DEFAULT 'video'"),
                ("preset_id", "TEXT DEFAULT 'miniapp_video'"),
                ("model", "TEXT DEFAULT 'v3_pro'"),
                ("duration", "INTEGER"),
                ("aspect_ratio", "TEXT"),
                ("prompt", "TEXT"),
                ("telegram_id", "BIGINT"),
                ("result_url", "TEXT"),
            ):
                await conn.execute(
                    f"ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS {name} {definition}"
                )
            await conn.commit()
        yield


async def create_delivery_task():
    async with await psycopg.AsyncConnection.connect(
        os.environ["DATABASE_URL"]
    ) as conn:
        cur = await conn.execute(
            "INSERT INTO users(telegram_id, credits) VALUES(891001, 100) "
            "ON CONFLICT(telegram_id) DO UPDATE SET credits = 100 RETURNING id"
        )
        uid = (await cur.fetchone())[0]
        cur = await conn.execute(
            "INSERT INTO generation_tasks(user_id, telegram_id, task_id, cost, status, request_data) "
            "VALUES(%s, 891001, 'durability-pg', 5, 'processing', '{}') RETURNING id",
            (uid,),
        )
        tid = (await cur.fetchone())[0]
        await conn.commit()
    return tid, uid


@pytest.mark.asyncio
async def test_pg_concurrent_result_storage_preserves_single_delivery_claim():
    await create_delivery_task()
    url = "https://cdn.example/result.mp4"
    stored = await asyncio.gather(
        *(database.store_task_result_ready("durability-pg", url) for _ in range(4))
    )
    assert all(stored)
    task = await database.get_task_by_id("durability-pg")
    assert (task.status, task.result_url) == ("completed", url)
    claims = await asyncio.gather(
        *(database.claim_task_delivery("durability-pg") for _ in range(4))
    )
    assert claims.count(True) == 1
    assert await database.store_task_result_ready("durability-pg", url)
    assert not await database.claim_task_delivery("durability-pg")
    task = await database.get_task_by_id("durability-pg")
    assert json.loads(task.request_data)["delivery_status"] == "delivering"
    # Exercise the production PostgreSQL JSON expression used by recovery.
    assert any(
        row["task_id"] == "durability-pg" for row in await get_stuck_tasks(minutes=0)
    )
    await database.mark_task_delivery_status("durability-pg", "delivered")
    assert not await database.claim_task_delivery("durability-pg")
    assert not await get_stuck_tasks(minutes=0)


@pytest.mark.asyncio
async def test_pg_result_persistence_and_failure_race_are_mutually_exclusive():
    tid, uid = await create_delivery_task()
    url = "https://cdn.example/result.mp4"
    _stored, failed = await asyncio.gather(
        database.store_task_result_ready("durability-pg", url),
        force_fail_task(tid, uid, 5),
    )
    task = await database.get_task_by_id("durability-pg")
    async with await psycopg.AsyncConnection.connect(
        os.environ["DATABASE_URL"]
    ) as conn:
        cur = await conn.execute("SELECT credits FROM users WHERE id = %s", (uid,))
        credits = (await cur.fetchone())[0]
    if failed:
        assert task.status == "failed"
        assert not task.result_url
        assert credits == 105
        assert not await database.store_task_result_ready("durability-pg", url)
    else:
        assert (task.status, task.result_url) == ("completed", url)
        assert credits == 100
        assert not await force_fail_task(tid, uid, 5)
