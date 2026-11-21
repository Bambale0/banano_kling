"""Bot login confirmation remains reachable without a channel subscription.

Authentication bypass must not bypass account bans or maintenance policy.
"""
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from aiogram import types

from bot import main


def _message(text: str):
    return types.Message(
        message_id=10,
        date=datetime.now(UTC),
        chat=types.Chat(id=88001337, type="private"),
        from_user=types.User(id=88001337, is_bot=False, first_name="Visitor"),
        text=text,
    )


def _callback(data: str):
    return types.CallbackQuery(
        id="callback-123",
        from_user=types.User(id=88001337, is_bot=False, first_name="Visitor"),
        chat_instance="chat-123",
        message=_message("Browser confirmation"),
        data=data,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("event", [
    _message("/start auth_" + "a" * 43),
    _callback("wba:yes:" + "a" * 43),
    _callback("wba:no:" + "a" * 43),
])
async def test_website_login_approval_bypasses_only_channel_subscription(
    monkeypatch, event,
):
    monkeypatch.setattr(main, "is_user_banned", AsyncMock(return_value=False))
    monkeypatch.setattr(main, "is_maintenance_mode_enabled", AsyncMock(return_value=False))
    channel = AsyncMock(return_value=True)
    monkeypatch.setattr(main, "is_channel_subscription_required", channel)
    handler = AsyncMock(return_value="handled")
    result = await main.AccessGuardMiddleware()(handler, event, {})
    assert result == "handled"
    handler.assert_awaited_once()
    channel.assert_not_awaited()


@pytest.mark.asyncio
async def test_banned_browser_login_approval_is_still_blocked(monkeypatch):
    monkeypatch.setattr(main, "is_user_banned", AsyncMock(return_value=True))
    monkeypatch.setattr(main, "is_maintenance_mode_enabled", AsyncMock(return_value=False))
    blocked = AsyncMock()
    monkeypatch.setattr(main.AccessGuardMiddleware, "_reply", blocked)
    handler = AsyncMock()
    await main.AccessGuardMiddleware()(handler, _message("/start auth_" + "a" * 43), {})
    handler.assert_not_awaited()
    blocked.assert_awaited_once()


def test_browser_approval_router_is_first_even_during_generation_fsm():
    dispatcher = main.setup_dispatcher()
    assert dispatcher.sub_routers[0].name == "telegram_browser_approval"


@pytest.mark.asyncio
async def test_approval_deep_link_does_not_reset_existing_telegram_fsm(monkeypatch):
    from bot.handlers import common, telegram_browser_approval_handlers as handlers

    user_created = AsyncMock()
    marked_available = AsyncMock()
    send = AsyncMock()
    sync = AsyncMock()
    monkeypatch.setattr(handlers, "get_or_create_user", user_created)
    monkeypatch.setattr(handlers, "mark_telegram_chat_available", marked_available)
    monkeypatch.setattr(handlers, "send_confirmation", send)
    monkeypatch.setattr(common, "_sync_telegram_profile", sync)

    message = _message("/start auth_" + "b" * 43)
    await handlers.browser_login_start(message)
    user_created.assert_awaited_once_with(88001337)
    marked_available.assert_awaited_once_with(88001337)
    send.assert_awaited_once_with(message, "b" * 43)
    sync.assert_awaited_once()
