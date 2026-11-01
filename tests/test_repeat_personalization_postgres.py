"""Repeat-personalization concurrency through the real PostgreSQL adapter."""

import asyncio
import os

import psycopg
import pytest

from bot import repeat_personalization as subject
from tests.runtime72_postgres_fixture import runtime_postgres_schema

pytestmark = pytest.mark.skipif(
    os.environ.get("RUNTIME_POSTGRES_TEST") != "1",
    reason="requires isolated PostgreSQL runtime CI",
)


BASE_PROMPT = "A person in a blue coat carries a chocolate cake."


def _fields(choice: str):
    return subject.normalize_repeat_fields(
        [
            {
                "key": "clothes",
                "label": "Одежда",
                "original_value": "blue coat",
                "choices": [choice],
            }
        ],
        prompt=BASE_PROMPT,
    )


@pytest.mark.asyncio
async def test_parallel_writes_observe_the_immediately_preceding_revision():
    async with runtime_postgres_schema():
        # The adapter deliberately skips SQLite-shaped application DDL. Its
        # native PostgreSQL bootstrap must therefore create this table before
        # the first ordinary read; the test must not pre-create it itself.
        assert await subject.get_repeat_fields(1) == []
        dsn = os.environ["DATABASE_URL"]
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            columns = await (
                await connection.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'generation_repeat_personalization'
                    """
                )
            ).fetchall()
            assert {row[0] for row in columns} >= {
                "generation_id",
                "fields_json",
                "write_token",
                "updated_by_telegram_id",
                "updated_at",
            }
            await connection.execute(
                "TRUNCATE generation_repeat_personalization"
            )
            row = await (
                await connection.execute(
                    "INSERT INTO generation_tasks(status) VALUES ('done') RETURNING id"
                )
            ).fetchone()
            await connection.commit()

        generation_id = int(row[0])
        initial = _fields("black coat")
        first = _fields("red dress")
        second = _fields("green jacket")
        await subject.save_repeat_fields(
            generation_id,
            initial,
            actor_telegram_id=1001,
        )

        results = await asyncio.gather(
            subject.save_repeat_fields(
                generation_id,
                first,
                actor_telegram_id=1002,
            ),
            subject.save_repeat_fields(
                generation_id,
                second,
                actor_telegram_id=1003,
            ),
        )

        previous_revisions = [previous for _token, previous in results]
        assert previous_revisions.count(initial) == 1
        assert sum(previous in (first, second) for previous in previous_revisions) == 1
        assert await subject.get_repeat_fields(generation_id) in (first, second)
