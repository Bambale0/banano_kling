"""Refund invariants through the real PostgreSQL transaction adapter."""
import asyncio
import json
import os
from unittest.mock import AsyncMock

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


async def create_task(*, request_data=None, telegram_id=741852):
    async with await psycopg.AsyncConnection.connect(os.environ['DATABASE_URL']) as connection:
        cursor = await connection.execute('''
            INSERT INTO users(telegram_id, credits) VALUES(%s, 100)
            ON CONFLICT(telegram_id) DO UPDATE SET credits = 100 RETURNING id
        ''', (telegram_id,))
        user_id = (await cursor.fetchone())[0]
        cursor = await connection.execute('''
            INSERT INTO generation_tasks(user_id, task_id, status, cost, request_data)
            VALUES(%s, 'current-provider-task', 'pending', 5, %s) RETURNING id
        ''', (user_id, json.dumps(request_data or {})))
        task_id = (await cursor.fetchone())[0]
        await connection.commit()
    return task_id, user_id


async def ensure_prompt_repeat_events_schema():
    async with await psycopg.AsyncConnection.connect(
        os.environ["DATABASE_URL"]
    ) as connection:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS prompt_repeat_events (
                id BIGSERIAL PRIMARY KEY,
                author_id BIGINT NOT NULL REFERENCES users(id),
                repeater_id BIGINT NOT NULL REFERENCES users(id),
                source_type TEXT NOT NULL,
                source_id BIGINT NOT NULL,
                repeat_task_id TEXT,
                credits_spent DOUBLE PRECISION DEFAULT 0,
                amount_rub DOUBLE PRECISION NOT NULL DEFAULT 10,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                uq_prompt_repeat_events_repeat_task_id
            ON prompt_repeat_events(repeat_task_id)
            WHERE repeat_task_id IS NOT NULL
              AND TRIM(repeat_task_id) <> ''
            """
        )
        await connection.commit()


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


@pytest.mark.asyncio
async def test_watchdog_does_not_refund_admin_legacy_row(monkeypatch):
    from bot.config import config

    monkeypatch.setattr(config, "ADMIN_IDS_STR", "741862")
    task_id, user_id = await create_task(telegram_id=741862)

    assert await force_fail_task(
        task_id,
        user_id,
        5,
        expected_provider_task_id="current-provider-task",
    ) is True

    status, data, completed_at, credits = await state(task_id, user_id)
    assert status == "failed"
    assert completed_at is not None
    assert credits == 100
    assert data.get("refund_claimed") is not True
    assert data.get("refund_state") != "refunded"


@pytest.mark.asyncio
async def test_watchdog_does_not_credit_explicitly_uncharged_admin_task():
    task_id, user_id = await create_task(
        request_data={
            "admin_free": True,
            "charged": False,
            "charged_cost": 0,
            "refund_on_failure": False,
            "refund_claimed": False,
        }
    )

    assert await force_fail_task(
        task_id,
        user_id,
        5,
        expected_provider_task_id="current-provider-task",
    ) is True

    status, data, completed_at, credits = await state(task_id, user_id)
    assert status == "failed"
    assert completed_at is not None
    assert credits == 100
    assert data["refund_claimed"] is False
    assert data.get("refund_state") != "refunded"


@pytest.mark.asyncio
async def test_seedance_edit_retry_claim_is_atomic_on_postgres(monkeypatch):
    """Webhook and reconciler may observe one failure, but launch one replacement."""
    from bot.handlers import seedance_25_fullstack as fullstack

    telegram_id = 741853
    old_task_id = "pg-seedance-edit-old"
    new_task_id = "pg-seedance-edit-new"
    request_data = {
        "seedance25_scenario": "multimodal",
        "seedance25_video_editing": False,
        "duration": 12,
        "aspect_ratio": "9:16",
        "reference_images": ["https://example.test/person.png"],
        "v_reference_videos": ["https://example.test/source.mp4"],
        "reference_audios": [],
        "resolution": "720p",
        "admin_free": True,
        "refund_on_failure": False,
    }
    async with await psycopg.AsyncConnection.connect(
        os.environ["DATABASE_URL"]
    ) as connection:
        await connection.execute(
            "ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS prompt TEXT"
        )
        await connection.execute(
            "ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS duration INTEGER"
        )
        await connection.execute(
            "ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS aspect_ratio TEXT"
        )
        await connection.execute(
            "ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS model TEXT"
        )
        await connection.execute(
            "ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS type TEXT"
        )
        cursor = await connection.execute(
            """
            INSERT INTO users(telegram_id, credits) VALUES(%s, 100)
            ON CONFLICT(telegram_id) DO UPDATE SET credits = 100 RETURNING id
            """,
            (telegram_id,),
        )
        user_id = (await cursor.fetchone())[0]
        await connection.execute(
            """
            INSERT INTO generation_tasks(
                user_id, task_id, status, cost, request_data,
                prompt, duration, aspect_ratio, model, type
            ) VALUES(
                %s, %s, 'pending', 0, %s, %s, 12, '9:16',
                'seedance_2_5', 'video'
            )
            """,
            (
                user_id,
                old_task_id,
                json.dumps(request_data),
                "Edit @Video1 with @Image1",
            ),
        )
        await connection.commit()

    started = asyncio.Event()
    release = asyncio.Event()

    async def launch(**_kwargs):
        started.set()
        await release.wait()
        return {"task_id": new_task_id}

    provider = AsyncMock(side_effect=launch)
    monkeypatch.setattr(fullstack.seedance_25_service, "generate_video", provider)
    fail_msg = (
        "Seedance identified your task as video editing; "
        "ratio must be adaptive and duration must be -1."
    )

    first = asyncio.create_task(
        fullstack._auto_retry_seedance25_video_editing(old_task_id, fail_msg)
    )
    await asyncio.wait_for(started.wait(), timeout=5)
    second = await fullstack._auto_retry_seedance25_video_editing(
        old_task_id, fail_msg
    )
    release.set()

    assert second is True
    assert await asyncio.wait_for(first, timeout=5) is True
    provider.assert_awaited_once()

    async with await psycopg.AsyncConnection.connect(
        os.environ["DATABASE_URL"]
    ) as connection:
        cursor = await connection.execute(
            """
            SELECT task_id, status, duration, aspect_ratio, request_data
            FROM generation_tasks
            WHERE task_id = %s
            """,
            (new_task_id,),
        )
        row = await cursor.fetchone()
    assert row is not None
    assert row[:4] == (new_task_id, "pending", -1, "adaptive")
    stored = json.loads(row[4])
    assert stored["task_id_aliases"] == [old_task_id, new_task_id]
    assert stored["seedance25_edit_auto_retry_attempt"] == 1


@pytest.mark.asyncio
async def test_prompt_repeat_reward_requires_positive_spend_on_postgres(monkeypatch):
    from bot import database

    await ensure_prompt_repeat_events_schema()
    async with await psycopg.AsyncConnection.connect(
        os.environ["DATABASE_URL"]
    ) as connection:
        await connection.execute("TRUNCATE prompt_repeat_events")
        author_cursor = await connection.execute(
            """
            INSERT INTO users(
                telegram_id, credits, partner_balance_rub,
                prompt_repeat_balance_rub, prompt_repeat_total_rub
            ) VALUES(741860, 100, 0, 0, 0)
            ON CONFLICT(telegram_id) DO UPDATE SET
                partner_balance_rub = 0,
                prompt_repeat_balance_rub = 0,
                prompt_repeat_total_rub = 0
            RETURNING id
            """
        )
        author_id = (await author_cursor.fetchone())[0]
        repeater_cursor = await connection.execute(
            """
            INSERT INTO users(telegram_id, credits) VALUES(741861, 100)
            ON CONFLICT(telegram_id) DO UPDATE SET credits = 100
            RETURNING id
            """
        )
        repeater_id = (await repeater_cursor.fetchone())[0]
        admin_cursor = await connection.execute(
            """
            INSERT INTO users(telegram_id, credits) VALUES(741862, 100)
            ON CONFLICT(telegram_id) DO UPDATE SET credits = 100
            RETURNING id
            """
        )
        admin_id = (await admin_cursor.fetchone())[0]
        await connection.commit()

    async with db_backend.connect() as db:
        for credits_spent in (0, float("nan"), float("inf")):
            assert await database._credit_prompt_repeat_reward_in_db(
                db,
                author_id=author_id,
                repeater_id=repeater_id,
                source_type="feed",
                source_id=123,
                repeat_task_id="postgres-free-repeat",
                credits_spent=credits_spent,
            ) is False
        await db.commit()

    async with await psycopg.AsyncConnection.connect(
        os.environ["DATABASE_URL"]
    ) as connection:
        cursor = await connection.execute(
            "SELECT COUNT(*) FROM prompt_repeat_events"
        )
        assert (await cursor.fetchone())[0] == 0
        cursor = await connection.execute(
            """
            SELECT partner_balance_rub, prompt_repeat_balance_rub,
                   prompt_repeat_total_rub
            FROM users WHERE id = %s
            """,
            (author_id,),
        )
        assert tuple(await cursor.fetchone()) == (0, 0, 0)

    from bot.config import config

    monkeypatch.setattr(config, "ADMIN_IDS_STR", "741862")
    async with db_backend.connect() as db:
        assert await database._credit_prompt_repeat_reward_in_db(
            db,
            author_id=author_id,
            repeater_id=admin_id,
            source_type="feed",
            source_id=123,
            repeat_task_id="postgres-admin-repeat",
            credits_spent=2.5,
        ) is False
        await db.commit()

    async with db_backend.connect() as db:
        assert await database._credit_prompt_repeat_reward_in_db(
            db,
            author_id=author_id,
            repeater_id=repeater_id,
            source_type="feed",
            source_id=123,
            repeat_task_id="postgres-paid-repeat",
            credits_spent=2.5,
        ) is True
        await db.commit()

    async with await psycopg.AsyncConnection.connect(
        os.environ["DATABASE_URL"]
    ) as connection:
        cursor = await connection.execute(
            """
            SELECT credits_spent, amount_rub
            FROM prompt_repeat_events
            WHERE repeat_task_id = %s
            """,
            ("postgres-paid-repeat",),
        )
        assert tuple(await cursor.fetchone()) == (2.5, 10)
        cursor = await connection.execute(
            """
            SELECT partner_balance_rub, prompt_repeat_balance_rub,
                   prompt_repeat_total_rub
            FROM users WHERE id = %s
            """,
            (author_id,),
        )
        assert tuple(await cursor.fetchone()) == (10, 10, 10)

@pytest.mark.asyncio
async def test_concurrent_prompt_repeat_reward_credits_once_on_postgres():
    from bot import database

    await ensure_prompt_repeat_events_schema()
    async with await psycopg.AsyncConnection.connect(
        os.environ["DATABASE_URL"]
    ) as connection:
        await connection.execute("TRUNCATE prompt_repeat_events")
        author_cursor = await connection.execute(
            """
            INSERT INTO users(
                telegram_id, credits, partner_balance_rub,
                prompt_repeat_balance_rub, prompt_repeat_total_rub
            ) VALUES(741870, 100, 0, 0, 0)
            ON CONFLICT(telegram_id) DO UPDATE SET
                partner_balance_rub = 0,
                prompt_repeat_balance_rub = 0,
                prompt_repeat_total_rub = 0
            RETURNING id
            """
        )
        author_id = (await author_cursor.fetchone())[0]
        repeater_cursor = await connection.execute(
            """
            INSERT INTO users(telegram_id, credits) VALUES(741871, 100)
            ON CONFLICT(telegram_id) DO UPDATE SET credits = 100
            RETURNING id
            """
        )
        repeater_id = (await repeater_cursor.fetchone())[0]
        await connection.commit()

    async def credit_once():
        from bot.postgres_aiosqlite import connect as direct_postgres_connect

        async with direct_postgres_connect() as db:
            credited = await database._credit_prompt_repeat_reward_in_db(
                db,
                author_id=author_id,
                repeater_id=repeater_id,
                source_type="feed",
                source_id=987,
                repeat_task_id="postgres-repeat-race",
                credits_spent=2.5,
            )
            if credited:
                await db.commit()
            return credited

    results = await asyncio.gather(*(credit_once() for _ in range(4)))
    assert results.count(True) == 1
    assert results.count(False) == 3

    async with await psycopg.AsyncConnection.connect(
        os.environ["DATABASE_URL"]
    ) as connection:
        cursor = await connection.execute(
            "SELECT COUNT(*) FROM prompt_repeat_events WHERE repeat_task_id = %s",
            ("postgres-repeat-race",),
        )
        assert (await cursor.fetchone())[0] == 1
        cursor = await connection.execute(
            """
            SELECT partner_balance_rub, prompt_repeat_balance_rub,
                   prompt_repeat_total_rub
            FROM users WHERE id = %s
            """,
            (author_id,),
        )
        assert tuple(await cursor.fetchone()) == (10, 10, 10)
