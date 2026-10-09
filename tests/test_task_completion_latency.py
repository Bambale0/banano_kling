"""Canonical completion must not parse other users' historical task payloads."""

import json
from contextlib import asynccontextmanager

import pytest

from bot import database
from bot import db as db_backend


@pytest.mark.asyncio
async def test_canonical_completion_avoids_historical_alias_scan(monkeypatch):
    user = await database.get_or_create_user(920001)
    async with db_backend.connect(database.DATABASE_PATH) as connection:
        await connection.executemany(
            "INSERT INTO generation_tasks (user_id, telegram_id, task_id, type, preset_id, status, request_data) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    user.id,
                    user.telegram_id,
                    f"history-{i}",
                    "video",
                    "test",
                    "completed",
                    json.dumps({"task_id_aliases": [f"legacy-{i}"]}),
                )
                for i in range(200)
            ],
        )
        await connection.commit()
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "current-provider-task",
        "video",
        "test",
        request_data={"task_id_aliases": ["local-current"]},
    )

    parsed_historical_payloads = []
    original_connect = db_backend.connect

    @asynccontextmanager
    async def instrumented_connect(*args, **kwargs):
        async with original_connect(*args, **kwargs) as connection:

            def json_valid(value):
                parsed_historical_payloads.append(value)
                try:
                    json.loads(value)
                    return 1
                except (TypeError, ValueError):
                    return 0

            await connection.create_function("json_valid", 1, json_valid)
            yield connection

    monkeypatch.setattr(db_backend, "connect", instrumented_connect)
    assert await database.complete_video_task(
        "current-provider-task", "https://example.test/result.mp4"
    )
    task = await database.get_task_by_id("current-provider-task")
    assert task.status == "completed"
    assert task.result_url == "https://example.test/result.mp4"
    assert parsed_historical_payloads == [], (
        "Canonical completion scanned unrelated historical JSON"
    )


@pytest.mark.asyncio
async def test_alias_then_canonical_completion_rewards_repeat_once():
    author = await database.get_or_create_user(920003)
    repeater = await database.get_or_create_user(920004)
    await database.add_generation_task(
        author.id,
        author.telegram_id,
        "latency-source",
        "image",
        "test",
        model="banana_pro",
        prompt="Source",
        cost=2,
    )
    await database.complete_video_task(
        "latency-source", "https://example.test/source.png"
    )
    source = await database.share_to_feed(
        "latency-source", author.id, publication_scope="profile"
    )
    assert source is not None
    await database.add_generation_task(
        repeater.id,
        repeater.telegram_id,
        "latency-repeat-provider",
        "image",
        "test",
        model="banana_pro",
        prompt="Repeat",
        cost=2,
        source_feed_gen_id=source["id"],
        request_data={"task_id_aliases": ["latency-repeat-local"]},
    )
    for task_id in [
        "latency-repeat-local",
        "latency-repeat-provider",
        "latency-repeat-local",
    ]:
        assert await database.complete_video_task(
            task_id, "https://example.test/repeat.png"
        )
    overview = await database.get_partner_overview(author.telegram_id)
    assert overview["prompt_repeat_balance_rub"] == 5
    assert overview["prompt_repeat_total_rub"] == 5
