"""Access policy errors must never re-execute a state-changing handler."""

from datetime import datetime, timezone

import pytest
from aiogram import types

from bot import main


@pytest.mark.asyncio
async def test_browser_login_handler_exception_is_not_replayed(monkeypatch):
    async def permitted(_user_id):
        return False

    async def maintenance_disabled():
        return False

    monkeypatch.setattr(main, "is_user_banned", permitted)
    monkeypatch.setattr(main, "is_maintenance_mode_enabled", maintenance_disabled)

    event = types.Message(
        message_id=1234,
        date=datetime.now(timezone.utc),
        chat=types.Chat(id=-100123, type="group"),
        from_user=types.User(id=987612345, is_bot=False, first_name="Test"),
        text="/start auth_test",
    )
    calls = 0

    async def handler(_event, _data):
        nonlocal calls
        calls += 1
        raise RuntimeError("downstream handler failed after side effect")

    with pytest.raises(RuntimeError, match="downstream handler"):
        await main.AccessGuardMiddleware()(handler, event, {})

    assert calls == 1
