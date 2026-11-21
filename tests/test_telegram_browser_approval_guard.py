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
