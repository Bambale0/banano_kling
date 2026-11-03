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
    mark_available.assert_not_awaited()
    mark_unavailable.assert_awaited_once_with(771002)


@pytest.mark.asyncio
async def test_transient_confirmation_failure_does_not_grant_delivery(monkeypatch):
    request = SimpleNamespace(app={"bot": SimpleNamespace(send_message=AsyncMock(side_effect=TimeoutError()))})
    monkeypatch.setattr(miniapp, "_miniapp_payload", AsyncMock(return_value={"init_data": "signed", "granted": True, "start_param_fallback": "feed_42_ref_PARTNER"}))
    context = AsyncMock(return_value=(771003, {}))
    monkeypatch.setattr(miniapp, "_get_user_context", context)
    available = AsyncMock()
    unavailable = AsyncMock()
    monkeypatch.setattr(miniapp, "mark_telegram_chat_available", available)
    monkeypatch.setattr(miniapp, "mark_telegram_chat_unavailable", unavailable)
    response = await miniapp.miniapp_write_access(request)
    body = json.loads(response.text)
    assert body["chat_available"] is False
    assert body["confirmation_sent"] is False
    assert body["needs_bot_start"] is False
    available.assert_not_awaited()
    unavailable.assert_not_awaited()
    context.assert_awaited_once_with(request.app, "signed", "feed_42_ref_PARTNER")


@pytest.mark.asyncio
async def test_delivery_proof_persistence_retries_without_resending(monkeypatch):
    from psycopg import OperationalError

    bot = SimpleNamespace(send_message=AsyncMock())
    request = SimpleNamespace(app={"bot": bot})
    monkeypatch.setattr(miniapp, "_miniapp_payload", AsyncMock(return_value={"init_data": "signed", "granted": True}))
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(771004, {})))
    available = AsyncMock(side_effect=[OperationalError("connection lost"), True])
    unavailable = AsyncMock()
    monkeypatch.setattr(miniapp, "mark_telegram_chat_available", available)
    monkeypatch.setattr(miniapp, "mark_telegram_chat_unavailable", unavailable)
    response = await miniapp.miniapp_write_access(request)
    assert response.status == 200
    assert json.loads(response.text)["chat_available"] is True
    assert available.await_count == 2
    bot.send_message.assert_awaited_once()
    unavailable.assert_not_awaited()


@pytest.mark.asyncio
async def test_persistent_proof_storage_outage_is_not_a_telegram_denial(monkeypatch):
    from psycopg import OperationalError

    bot = SimpleNamespace(send_message=AsyncMock())
    request = SimpleNamespace(app={"bot": bot})
    monkeypatch.setattr(miniapp, "_miniapp_payload", AsyncMock(return_value={"init_data": "signed", "granted": True}))
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(771005, {})))
    available = AsyncMock(side_effect=OperationalError("connection lost"))
    unavailable = AsyncMock()
    monkeypatch.setattr(miniapp, "mark_telegram_chat_available", available)
    monkeypatch.setattr(miniapp, "mark_telegram_chat_unavailable", unavailable)
    response = await miniapp.miniapp_write_access(request)
    assert response.status == 503
    assert json.loads(response.text)["code"] == "database_unavailable"
    assert available.await_count == 2
    bot.send_message.assert_awaited_once()
    unavailable.assert_not_awaited()
