"""Runtime reliability tests: idempotency, locks, and credit ledger."""

import importlib
from types import SimpleNamespace

import pytest


def _reload_database(monkeypatch, db_path):
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    import bot.database as database
    return importlib.reload(database)


@pytest.mark.asyncio
async def test_credit_ledger_records_add_and_deduct(tmp_path, monkeypatch):
    db = _reload_database(monkeypatch, tmp_path / "ledger.db")
    await db.init_db()
    await db.get_or_create_user(111)

    assert await db.add_credits(111, 7, reason="test_add", external_id="add-1")
    assert await db.deduct_credits(111, 3, reason="test_charge", external_id="charge-1")

    assert await db.get_user_credits(111) == 14
    rows = await db.get_credit_transactions(111)
    assert [(r["amount"], r["reason"], r["external_id"]) for r in rows] == [
        (7, "test_add", "add-1"),
        (-3, "test_charge", "charge-1"),
    ]


@pytest.mark.asyncio
async def test_add_credits_once_is_idempotent(tmp_path, monkeypatch):
    db = _reload_database(monkeypatch, tmp_path / "ledger_once.db")
    await db.init_db()
    await db.get_or_create_user(222)

    assert await db.add_credits_once(222, 5, reason="refund", external_id="task-1") is True
    assert await db.add_credits_once(222, 5, reason="refund", external_id="task-1") is False

    assert await db.get_user_credits(222) == 15
    rows = await db.get_credit_transactions(222)
    assert len([r for r in rows if r["reason"] == "refund" and r["external_id"] == "task-1"]) == 1


@pytest.mark.asyncio
async def test_runtime_reliability_service_blocks_duplicate_events_and_locks():
    from bot.services.reliability import RuntimeReliability
    from bot.services.redis_service import NullRedisService

    reliability = RuntimeReliability(NullRedisService())

    assert await reliability.mark_provider_event("kie", "task-1", "failed") is True
    assert await reliability.mark_provider_event("kie", "task-1", "failed") is False
    assert await reliability.mark_telegram_update(12345) is True
    assert await reliability.mark_telegram_update(12345) is False
    assert await reliability.acquire_generation_lock(777) is True
    assert await reliability.acquire_generation_lock(777) is False
    await reliability.release_generation_lock(777)
    assert await reliability.acquire_generation_lock(777) is True


@pytest.mark.asyncio
async def test_user_profile_sync_middleware_updates_event_user(monkeypatch):
    import bot.main as main

    calls = []

    async def fake_get_or_create_user(
        telegram_id,
        username=None,
        first_name=None,
        last_name=None,
    ):
        calls.append((telegram_id, username, first_name, last_name))

    monkeypatch.setattr(main, "get_or_create_user", fake_get_or_create_user)
    middleware = main.UserProfileSyncMiddleware()
    event = SimpleNamespace(
        from_user=SimpleNamespace(
            id=555,
            is_bot=False,
            username="fresh_user",
            first_name="Fresh",
            last_name="Name",
        )
    )

    async def handler(received_event, data):
        data["handled"] = received_event is event
        return "ok"

    data = {}
    result = await middleware(handler, event, data)

    assert result == "ok"
    assert data["handled"] is True
    assert calls == [(555, "fresh_user", "Fresh", "Name")]


@pytest.mark.asyncio
async def test_register_user_bot_commands_excludes_admin_commands():
    import bot.main as main

    class FakeBot:
        def __init__(self):
            self.commands = None

        async def set_my_commands(self, commands):
            self.commands = commands

    bot = FakeBot()

    await main._register_user_bot_commands(bot)

    command_names = [command.command for command in bot.commands]
    assert command_names == ["start", "help", "feed", "ref", "earn", "clear"]
    assert "admin" not in command_names
    assert not any(command.startswith("admin_") for command in command_names)
