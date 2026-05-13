"""Runtime reliability tests: idempotency, locks, and credit ledger."""

import importlib

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
