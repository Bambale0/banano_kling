import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import miniapp


@pytest.mark.asyncio
async def test_write_access_confirmation_marks_chat_available(monkeypatch):
    bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=10)))
    request = SimpleNamespace(app={"bot": bot})
    monkeypatch.setattr(
        miniapp,
        "_miniapp_payload",
        AsyncMock(return_value={"init_data": "signed", "granted": True}),
    )
    monkeypatch.setattr(
        miniapp,
        "_get_user_context",
        AsyncMock(return_value=(771001, {})),
    )
    mark_available = AsyncMock(return_value=True)
    monkeypatch.setattr(miniapp, "mark_telegram_chat_available", mark_available)

    response = await miniapp.miniapp_write_access(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload == {
        "ok": True,
        "chat_available": True,
        "confirmation_sent": True,
        "needs_bot_start": False,
    }
    mark_available.assert_awaited_once_with(771001)
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_write_access_requires_explicit_grant(monkeypatch):
    request = SimpleNamespace(app={"bot": SimpleNamespace()})
    monkeypatch.setattr(
        miniapp,
        "_miniapp_payload",
        AsyncMock(return_value={"init_data": "signed", "granted": False}),
    )
    monkeypatch.setattr(
        miniapp,
        "_get_user_context",
        AsyncMock(return_value=(771001, {})),
    )

    response = await miniapp.miniapp_write_access(request)
    payload = json.loads(response.text)

    assert response.status == 400
    assert payload["ok"] is False
    assert payload["error"] == "write_access_not_granted"


@pytest.mark.asyncio
async def test_write_access_terminal_confirmation_requires_bot_start(monkeypatch):
    bot = SimpleNamespace(
        send_message=AsyncMock(side_effect=RuntimeError("Bad Request: chat not found"))
    )
    request = SimpleNamespace(app={"bot": bot})
    monkeypatch.setattr(
        miniapp,
        "_miniapp_payload",
        AsyncMock(return_value={"init_data": "signed", "granted": True}),
    )
    monkeypatch.setattr(
        miniapp,
        "_get_user_context",
        AsyncMock(return_value=(771002, {})),
    )
    mark_available = AsyncMock(return_value=True)
    mark_unavailable = AsyncMock(return_value=True)
    monkeypatch.setattr(miniapp, "mark_telegram_chat_available", mark_available)
    monkeypatch.setattr(miniapp, "mark_telegram_chat_unavailable", mark_unavailable)

    response = await miniapp.miniapp_write_access(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["chat_available"] is False
    assert payload["confirmation_sent"] is False
    assert payload["needs_bot_start"] is True
    mark_available.assert_awaited_once_with(771002)
    mark_unavailable.assert_awaited_once_with(771002)
