import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from unittest.mock import AsyncMock

import aiosqlite
import pytest
import pytest_asyncio
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from bot.database import get_or_create_user, get_user_credits, init_db
from bot.services.push_scenario_dispatcher import (
    build_push_scenario_text,
    dispatch_due_push_scenarios,
    send_push_scenario_event,
)
from bot.services.push_scenario_service import (
    PUSH_SCENARIO_CONFIG_KEY,
    BotSettingsJsonStore,
    PushScenarioConfig,
    PushScenarioEvent,
    PushScenarioService,
)


@pytest_asyncio.fixture(scope="function")
async def temp_db():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)

    with patch("bot.database.DATABASE_PATH", db_path):
        await init_db()
        yield db_path

    os.unlink(db_path)


def _ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(tzinfo=None).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


async def _set_user_timestamps(
    db_path: str,
    telegram_id: int,
    *,
    created_at: datetime,
    updated_at: datetime | None = None,
    has_paid: bool = False,
) -> int:
    user = await get_or_create_user(telegram_id)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            UPDATE users
            SET created_at = ?, updated_at = ?, has_paid = ?
            WHERE id = ?
            """,
            (
                _ts(created_at),
                _ts(updated_at or created_at),
                1 if has_paid else 0,
                user.id,
            ),
        )
        await db.commit()
    return user.id


async def _insert_generation_task(
    db_path: str,
    *,
    user_id: int,
    telegram_id: int,
    task_id: str,
    status: str,
    created_at: datetime,
    completed_at: datetime | None = None,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO generation_tasks (
                user_id, telegram_id, task_id, type, preset_id, status,
                created_at, completed_at, result_url
            )
            VALUES (?, ?, ?, 'image', 'test', ?, ?, ?, ?)
            """,
            (
                user_id,
                telegram_id,
                task_id,
                status,
                _ts(created_at),
                _ts(completed_at) if completed_at else None,
                "https://example.test/result.png" if status == "completed" else None,
            ),
        )
        await db.commit()


@pytest.mark.asyncio
async def test_bot_settings_store_roundtrips_json(temp_db):
    store = BotSettingsJsonStore()
    value = {"enabled": False, "rules": []}

    await store.set_json(PUSH_SCENARIO_CONFIG_KEY, value)

    assert await store.get_json(PUSH_SCENARIO_CONFIG_KEY, {}) == value


@pytest.mark.asyncio
async def test_collect_due_events_for_all_default_scenarios(temp_db):
    now = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)

    abandoned_user_id = await _set_user_timestamps(
        temp_db,
        1001,
        created_at=now - timedelta(hours=3),
        updated_at=now - timedelta(minutes=10),
    )
    await _insert_generation_task(
        temp_db,
        user_id=abandoned_user_id,
        telegram_id=1001,
        task_id="pending-old",
        status="pending",
        created_at=now - timedelta(hours=2),
    )

    await _set_user_timestamps(
        temp_db,
        1002,
        created_at=now - timedelta(hours=25),
        updated_at=now - timedelta(hours=2),
    )

    await _set_user_timestamps(
        temp_db,
        1003,
        created_at=now - timedelta(days=10),
        updated_at=now - timedelta(days=8),
        has_paid=True,
    )

    first_success_user_id = await _set_user_timestamps(
        temp_db,
        1004,
        created_at=now - timedelta(days=1),
        updated_at=now - timedelta(minutes=5),
        has_paid=True,
    )
    await _insert_generation_task(
        temp_db,
        user_id=first_success_user_id,
        telegram_id=1004,
        task_id="first-done",
        status="completed",
        created_at=now - timedelta(minutes=20),
        completed_at=now - timedelta(minutes=10),
    )

    events = await PushScenarioService().collect_due_events(now=now, limit=20)
    by_scenario = {event.scenario_key: event for event in events}

    assert set(by_scenario) == {
        "generation_abandoned",
        "payment_abandoned",
        "inactive_user",
        "first_generation_success",
    }
    assert by_scenario["generation_abandoned"].payload["task_id"] == "pending-old"
    assert by_scenario["payment_abandoned"].payload["bonus_credits"] == 1
    assert by_scenario["inactive_user"].payload["promo_code"] == "COMEBACK7"
    assert by_scenario["first_generation_success"].payload["package_code"] == "starter"


@pytest.mark.asyncio
async def test_collect_due_events_ignores_not_due_and_paid_users(temp_db):
    now = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
    recent_user_id = await _set_user_timestamps(
        temp_db,
        2001,
        created_at=now - timedelta(minutes=30),
        updated_at=now - timedelta(minutes=30),
    )
    await _insert_generation_task(
        temp_db,
        user_id=recent_user_id,
        telegram_id=2001,
        task_id="pending-recent",
        status="pending",
        created_at=now - timedelta(minutes=30),
    )
    await _set_user_timestamps(
        temp_db,
        2002,
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(minutes=5),
        has_paid=True,
    )

    events = await PushScenarioService().collect_due_events(now=now, limit=20)

    assert events == []


@pytest.mark.asyncio
async def test_collect_due_events_can_mark_enqueued_to_dedupe(temp_db):
    now = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
    user_id = await _set_user_timestamps(
        temp_db,
        3001,
        created_at=now - timedelta(hours=25),
        updated_at=now - timedelta(minutes=5),
    )
    await _insert_generation_task(
        temp_db,
        user_id=user_id,
        telegram_id=3001,
        task_id="pending-old",
        status="pending",
        created_at=now - timedelta(hours=2),
    )

    service = PushScenarioService()
    first = await service.collect_due_events(now=now, mark_enqueued=True)
    second = await service.collect_due_events(now=now + timedelta(minutes=1))

    assert first
    assert second == []


@pytest.mark.asyncio
async def test_disabled_config_returns_no_events(temp_db):
    now = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
    await _set_user_timestamps(
        temp_db,
        4001,
        created_at=now - timedelta(hours=25),
        updated_at=now - timedelta(days=8),
    )
    service = PushScenarioService()
    await service.save_config(PushScenarioConfig(enabled=False))

    assert await service.collect_due_events(now=now) == []


@pytest.mark.asyncio
async def test_dispatch_due_push_scenarios_sends_and_marks_event(temp_db):
    now = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
    await _set_user_timestamps(
        temp_db,
        5001,
        created_at=now - timedelta(hours=25),
        updated_at=now - timedelta(minutes=5),
    )
    service = PushScenarioService()
    bot = AsyncMock()

    with patch("bot.services.push_scenario_service._utc_now", return_value=now):
        stats = await dispatch_due_push_scenarios(
            bot, service, limit=10, sleep_seconds=0
        )
        second = await dispatch_due_push_scenarios(
            bot, service, limit=10, sleep_seconds=0
        )

    assert stats == {"due": 1, "sent": 1, "failed": 0, "skipped": 0}
    assert second == {"due": 0, "sent": 0, "failed": 0, "skipped": 0}
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["chat_id"] == 5001


@pytest.mark.asyncio
async def test_payment_abandoned_push_bonus_is_idempotent(temp_db):
    now = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
    await _set_user_timestamps(
        temp_db,
        5002,
        created_at=now - timedelta(hours=25),
        updated_at=now - timedelta(minutes=5),
    )
    before = await get_user_credits(5002)
    service = PushScenarioService()
    bot = AsyncMock()

    with patch("bot.services.push_scenario_service._utc_now", return_value=now):
        first = await dispatch_due_push_scenarios(
            bot, service, limit=10, sleep_seconds=0
        )
        second = await dispatch_due_push_scenarios(
            bot, service, limit=10, sleep_seconds=0
        )

    assert first["sent"] == 1
    assert second["due"] == 0
    assert await get_user_credits(5002) == before + 1


@pytest.mark.asyncio
async def test_dispatch_sends_only_one_message_per_user_during_cooldown(temp_db):
    now = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
    await _set_user_timestamps(
        temp_db,
        5004,
        created_at=now - timedelta(days=10),
        updated_at=now - timedelta(days=8),
    )
    service = PushScenarioService()
    bot = AsyncMock()

    with patch("bot.services.push_scenario_service._utc_now", return_value=now):
        stats = await dispatch_due_push_scenarios(
            bot,
            service,
            limit=10,
            sleep_seconds=0,
            user_cooldown_seconds=86400,
        )

    assert stats["due"] >= 2
    assert stats["sent"] == 1
    assert stats["skipped"] == stats["due"] - 1
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_blocked_user_event_is_marked_to_avoid_retry(temp_db):
    now = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
    await _set_user_timestamps(
        temp_db,
        5003,
        created_at=now - timedelta(hours=25),
        updated_at=now - timedelta(minutes=5),
    )
    service = PushScenarioService()
    events = await service.collect_due_events(now=now, limit=1)
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramForbiddenError(
        method=SendMessage(chat_id=5003, text="test"),
        message="Forbidden: bot was blocked by the user",
    )

    sent = await send_push_scenario_event(bot, events[0], service)
    second = await service.collect_due_events(now=now, limit=1)

    assert sent is False
    assert second == []


def test_build_push_scenario_text_includes_bonus_and_promo():
    text = build_push_scenario_text(
        PushScenarioEvent(
            scenario_key="inactive_user",
            user_id=1,
            telegram_id=2,
            due_at=datetime(2026, 5, 31, tzinfo=timezone.utc),
            event_key="inactive_user:1",
            title="Давно не заходил",
            message="Вернитесь за новой генерацией",
            payload={"promo_code": "COMEBACK7", "bonus_credits": 3},
        )
    )

    assert "COMEBACK7" in text
    assert "3" in text
