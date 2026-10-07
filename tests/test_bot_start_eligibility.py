"""Never-started offers use positive lifecycle evidence, never delivery failures.

Every row is an isolated SQLite fixture; all Telegram/provider boundaries are mocked.
"""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import types

from bot import database, miniapp
from bot import db as db_backend


async def chat_state(telegram_id):
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        row = await (
            await db.execute(
                "SELECT telegram_chat_state FROM users WHERE telegram_id = ?",
                (telegram_id,),
            )
        ).fetchone()
    return row["telegram_chat_state"] if row else None


@pytest.mark.asyncio
async def test_new_miniapp_marker_is_one_way_and_does_not_reset_existing_users():
    user = await database.get_or_create_user(
        880001, initial_telegram_chat_state="never_started"
    )
    assert await database.needs_telegram_bot_start(user.telegram_id) is True
    assert await database.can_attempt_telegram_delivery(user.telegram_id) is False
    original_credits = user.credits
    await database.get_or_create_user(
        user.telegram_id, initial_telegram_chat_state="never_started"
    )
    await database.mark_telegram_chat_available(user.telegram_id)
    await database.mark_telegram_chat_unavailable(user.telegram_id)
    await database.get_or_create_user(
        user.telegram_id, initial_telegram_chat_state="never_started"
    )
    assert await database.needs_telegram_bot_start(user.telegram_id) is False
    assert await chat_state(user.telegram_id) == "unavailable"
    assert (
        await database.get_or_create_user(user.telegram_id)
    ).credits == original_credits


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [None, "available", "unavailable", "future_unknown"])
async def test_legacy_and_unknown_states_never_receive_offer(state):
    user = await database.get_or_create_user(880002)
    async with db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE users SET telegram_chat_state = ? WHERE telegram_id = ?",
            (state, user.telegram_id),
        )
        await db.commit()
    await database.get_or_create_user(
        user.telegram_id, initial_telegram_chat_state="never_started"
    )
    assert await database.needs_telegram_bot_start(user.telegram_id) is False
    assert await chat_state(user.telegram_id) == state


@pytest.mark.asyncio
async def test_missing_user_is_unknown_not_never_started():
    assert await database.needs_telegram_bot_start(889999) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery_status", ["unavailable", "delivered", "link_sent"])
async def test_task_delivery_transitions_preserve_or_retire_marker(delivery_status):
    user = await database.get_or_create_user(
        880003, initial_telegram_chat_state="never_started"
    )
    await database.mark_telegram_chat_unavailable(user.telegram_id)
    assert await database.needs_telegram_bot_start(user.telegram_id) is True
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "never-started-task",
        "image",
        "miniapp_image",
        request_data={"source": "miniapp"},
    )
    assert await database.mark_task_delivery_status(
        "never-started-task", delivery_status
    )
    expected_offer = delivery_status == "unavailable"
    assert await database.needs_telegram_bot_start(user.telegram_id) is expected_offer
    assert await chat_state(user.telegram_id) == (
        "never_started" if expected_offer else "available"
    )
    if not expected_offer:
        await database.mark_task_delivery_status("never-started-task", "unavailable")
        assert await database.needs_telegram_bot_start(user.telegram_id) is False


@pytest.mark.asyncio
async def test_transient_probe_is_not_positive_history_but_successful_probe_is():
    user = await database.get_or_create_user(
        880004, initial_telegram_chat_state="never_started"
    )
    transient = AsyncMock(side_effect=TimeoutError("synthetic timeout"))
    assert (
        await database.can_attempt_telegram_delivery(user.telegram_id, probe=transient)
        is True
    )
    assert await database.needs_telegram_bot_start(user.telegram_id) is True
    terminal = AsyncMock(side_effect=RuntimeError("Bad Request: chat not found"))
    assert (
        await database.can_attempt_telegram_delivery(user.telegram_id, probe=terminal)
        is False
    )
    assert await database.needs_telegram_bot_start(user.telegram_id) is True
    success = AsyncMock(return_value=object())
    assert (
        await database.can_attempt_telegram_delivery(user.telegram_id, probe=success)
        is True
    )
    assert await database.needs_telegram_bot_start(user.telegram_id) is False


def signed_context(monkeypatch, user):
    monkeypatch.setattr(miniapp, "_validate_init_data", lambda *_args: {"user": user})
    monkeypatch.setattr(
        miniapp, "is_channel_subscription_required", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(miniapp, "update_user_profile", AsyncMock())


@pytest.mark.asyncio
@pytest.mark.parametrize("permission", [None, False, "true", True])
async def test_only_signed_boolean_positive_retires_new_miniapp_offer(
    monkeypatch, permission
):
    signed_user = {"id": 880005, "first_name": "Fixture"}
    if permission is not None:
        signed_user["allows_write_to_pm"] = permission
    signed_context(monkeypatch, signed_user)
    telegram_id, _ = await miniapp._get_user_context({}, "synthetic-signed-data")
    assert await database.needs_telegram_bot_start(telegram_id) is (
        permission is not True
    )
    # Signed permission is historical, not a current reachability probe.
    assert await database.can_attempt_telegram_delivery(telegram_id) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("initial", ["never_started", "unavailable", "available", None])
async def test_signed_positive_is_permanent_without_overwriting_current_reachability(
    monkeypatch, initial
):
    user = await database.get_or_create_user(
        880006, initial_telegram_chat_state=initial
    )
    signed_user = {
        "id": user.telegram_id,
        "first_name": "Fixture",
        "allows_write_to_pm": True,
    }
    signed_context(monkeypatch, signed_user)
    await miniapp._get_user_context({}, "synthetic-signed-data")
    assert await database.needs_telegram_bot_start(user.telegram_id) is False
    assert await chat_state(user.telegram_id) == (
        "unavailable" if initial == "never_started" else initial
    )
    signed_user.pop("allows_write_to_pm")
    await miniapp._get_user_context({}, "next-synthetic-signed-data")
    assert await database.needs_telegram_bot_start(user.telegram_id) is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state,expected", [("never_started", True), ("unavailable", False), (None, False)]
)
async def test_bootstrap_exposes_explicit_offer_independent_of_delivery(
    monkeypatch, state, expected
):
    user = await database.get_or_create_user(880007, initial_telegram_chat_state=state)
    monkeypatch.setattr(
        miniapp, "_miniapp_payload", AsyncMock(return_value={"init_data": "fixture"})
    )
    monkeypatch.setattr(
        miniapp,
        "_get_user_context",
        AsyncMock(
            return_value=(
                user.telegram_id,
                {"user": user, "payload": {"user": {"id": user.telegram_id}}},
            )
        ),
    )
    monkeypatch.setattr(
        miniapp,
        "_cached_bot_me",
        AsyncMock(return_value=SimpleNamespace(username="fixture_bot")),
    )
    monkeypatch.setattr(miniapp, "_fetch_recent_tasks", AsyncMock(return_value=[]))
    monkeypatch.setattr(miniapp, "get_partner_overview", AsyncMock(return_value={}))
    monkeypatch.setattr(miniapp, "list_saved_references", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        miniapp, "get_and_clear_miniapp_notifications", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(miniapp.preset_manager, "get_packages", list)
    monkeypatch.setattr(miniapp, "IMAGE_MODELS", [])
    monkeypatch.setattr(miniapp, "VIDEO_MODELS", [])
    response = await miniapp.miniapp_bootstrap(SimpleNamespace(app={}))
    assert response.status == 200
    payload = json.loads(response.text)
    assert payload["telegram_bot_start_required"] is expected
    assert payload["telegram_chat_available"] is (state is None)


def message(telegram_id, chat_type="private", chat_id=None):
    return types.Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=types.Chat(id=telegram_id if chat_id is None else chat_id, type=chat_type),
        from_user=types.User(id=telegram_id, is_bot=False, first_name="Fixture"),
        text="/start",
    )


def guard_with_mocked_boundaries(monkeypatch, blocked=False):
    from bot import main

    guard = main.AccessGuardMiddleware()
    monkeypatch.setattr(main.config, "is_admin", lambda _id: False)
    monkeypatch.setattr(main, "is_user_banned", AsyncMock(return_value=blocked))
    monkeypatch.setattr(
        main, "is_maintenance_mode_enabled", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        main, "is_channel_subscription_required", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(guard, "_reply", AsyncMock())
    return guard


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["message", "callback", "banned"])
async def test_private_updates_retire_offer_before_access_guard_without_bypassing_it(
    monkeypatch, kind
):
    user = await database.get_or_create_user(
        880008, initial_telegram_chat_state="never_started"
    )
    event = message(user.telegram_id)
    if kind == "callback":
        event = types.CallbackQuery(
            id="fixture-query",
            from_user=event.from_user,
            message=event,
            chat_instance="fixture-chat",
            data="menu_balance",
        )
    guard = guard_with_mocked_boundaries(monkeypatch, blocked=kind == "banned")
    handler = AsyncMock(return_value="handled")
    result = await guard(handler, event, {})
    assert await database.needs_telegram_bot_start(user.telegram_id) is False
    assert await chat_state(user.telegram_id) == "available"
    if kind == "banned":
        assert result is None
        handler.assert_not_awaited()
    else:
        assert result == "handled"
        handler.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["group", "inline_callback", "other_private"])
async def test_non_private_owner_updates_do_not_claim_chat_history(monkeypatch, kind):
    user = await database.get_or_create_user(
        880009, initial_telegram_chat_state="never_started"
    )
    if kind == "group":
        event = message(user.telegram_id, "group", -100)
    elif kind == "other_private":
        event = message(user.telegram_id, "private", 887777)
    else:
        event = types.CallbackQuery(
            id="fixture-query",
            from_user=message(user.telegram_id).from_user,
            inline_message_id="fixture-inline",
            chat_instance="fixture",
            data="menu_balance",
        )
    handler = AsyncMock(return_value="handled")
    await guard_with_mocked_boundaries(monkeypatch)(handler, event, {})
    assert await database.needs_telegram_bot_start(user.telegram_id) is True
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_private_contact_before_user_creation_survives_later_miniapp_creation(
    monkeypatch,
):
    handler = AsyncMock(return_value="handled")
    await guard_with_mocked_boundaries(monkeypatch)(handler, message(880010), {})
    first = await database.get_or_create_user(880010)
    later = await database.get_or_create_user(
        880010, initial_telegram_chat_state="never_started"
    )
    assert first.id == later.id
    assert first.credits == later.credits
    assert first.referral_code == later.referral_code
    assert first.referred_by == later.referred_by is None
    assert await database.needs_telegram_bot_start(880010) is False


@pytest.mark.asyncio
async def test_private_history_recording_error_does_not_bypass_access_guard(
    monkeypatch,
):
    guard = guard_with_mocked_boundaries(monkeypatch, blocked=True)
    monkeypatch.setattr(
        database,
        "get_or_create_user",
        AsyncMock(side_effect=RuntimeError("synthetic storage error")),
    )
    handler = AsyncMock(return_value="must not run")
    event = message(880011)
    assert await guard(handler, event, {}) is None
    guard._reply.assert_awaited_once_with(event, "⛔ Доступ к боту ограничен.")
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_image_success_retires_marker_after_inconclusive_probe(monkeypatch):
    user = await database.get_or_create_user(
        880012, initial_telegram_chat_state="never_started",
    )
    bot = SimpleNamespace(
        get_chat=AsyncMock(side_effect=TimeoutError("synthetic timeout")),
        send_document=AsyncMock(return_value=SimpleNamespace(message_id=42)),
    )
    monkeypatch.setattr(miniapp, "get_image_result_keyboard", lambda *_args, **_kwargs: None)
    await miniapp._deliver_miniapp_direct_image_result(
        {"bot": bot}, user.telegram_id,
        {"status": "done", "saved_url": "https://test.example.com/result.png", "task_id": "fixture-direct"},
        img_service="banana_pro", img_ratio="1:1", unit_cost=0, prompt_hidden=False,
    )
    bot.send_document.assert_awaited_once()
    assert await database.needs_telegram_bot_start(user.telegram_id) is False


@pytest.mark.asyncio
async def test_direct_image_proof_error_cannot_reclassify_successful_delivery(monkeypatch):
    bot = SimpleNamespace(
        get_chat=AsyncMock(return_value=object()),
        send_document=AsyncMock(return_value=SimpleNamespace(message_id=43)),
    )
    monkeypatch.setattr(miniapp, "can_attempt_telegram_delivery", AsyncMock(return_value=True))
    monkeypatch.setattr(miniapp, "get_image_result_keyboard", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        miniapp, "mark_telegram_chat_available",
        AsyncMock(side_effect=RuntimeError("chat not found in synthetic proof store")),
    )
    delivery_status = AsyncMock()
    monkeypatch.setattr(miniapp, "mark_task_delivery_status", delivery_status)
    await miniapp._deliver_miniapp_direct_image_result(
        {"bot": bot}, 880013,
        {"status": "done", "saved_url": "https://test.example.com/result.png", "task_id": "fixture-proof-error"},
        img_service="banana_pro", img_ratio="1:1", unit_cost=0, prompt_hidden=False,
    )
    bot.send_document.assert_awaited_once()
    delivery_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_positive_history_write_failure_cannot_rollback_delivery_receipt(monkeypatch):
    user = await database.get_or_create_user(
        880014, initial_telegram_chat_state="never_started",
    )
    await database.add_generation_task(
        user.id, user.telegram_id, "fixture-delivery-receipt", "image", "miniapp_image",
        request_data={"source": "miniapp"},
    )
    monkeypatch.setattr(
        database, "mark_telegram_chat_available",
        AsyncMock(side_effect=RuntimeError("synthetic proof storage error")),
    )
    assert await database.mark_task_delivery_status("fixture-delivery-receipt", "delivered") is True
    task = await database.get_task_by_id("fixture-delivery-receipt")
    assert json.loads(task.request_data)["delivery_status"] == "delivered"
    database.mark_telegram_chat_available.assert_awaited_once_with(user.telegram_id)
