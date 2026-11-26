from __future__ import annotations

import pytest

from bot import database
from bot.services.freekassa_service import FreeKassaService


def service(monkeypatch):
    for key, value in {
        "FREEKASSA_MERCHANT_ID": "7012",
        "FREEKASSA_SECRET_WORD": "test-secret",
        "FREEKASSA_SECRET_WORD_2": "test-secret-2",
        "FREEKASSA_API_KEY": "test-key",
    }.items():
        monkeypatch.setenv(key, value)
    instance = FreeKassaService()

    async def lookup(**_kwargs):
        return None

    monkeypatch.setattr(instance, "get_payment", lookup)
    return instance


async def insert_orders(user_id, start, count, provider="freekassa"):
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        for i in range(start, start + count):
            await db.execute(
                "INSERT INTO transactions (order_id, user_id, provider, credits, "
                "amount_rub, status, created_at) VALUES (?, ?, ?, 1, 100, 'pending', ?)",
                (f"{provider}-{i}", user_id, provider, f"2026-01-01 00:{i // 60:02d}:{i % 60:02d}"),
            )
        await db.commit()


@pytest.mark.asyncio
async def test_history_progresses_even_with_new_orders_and_restart(monkeypatch):
    user = await database.get_or_create_user(12345)
    await insert_orders(user.id, 0, 20)
    await insert_orders(user.id, 0, 3, "lava")
    current = service(monkeypatch)
    historical = []
    for cycle in range(10):
        await insert_orders(user.id, 100 + cycle * 4, 4)
        if cycle == 5:
            current = service(monkeypatch)
        rows = await current.poll_pending_transactions(limit=5)
        ids = [row["order_id"] for row in rows]
        assert len(ids) == len(set(ids)) == 5
        assert f"freekassa-{cycle}" in ids
        assert {f"freekassa-{i}" for i in range(100 + cycle * 4, 104 + cycle * 4)} <= set(ids)
        assert all(row["action"] == "not_found" for row in rows)
        historical.extend(row["order_id"] for row in rows if row.get("scan_lane") == "history")
    assert historical == [f"freekassa-{i}" for i in range(10)]
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        count = await (await db.execute("SELECT COUNT(*) FROM transactions WHERE status='pending'")).fetchone()
    assert count[0] == 63


@pytest.mark.asyncio
async def test_history_wraps_without_duplicate_requests(monkeypatch):
    user = await database.get_or_create_user(12345)
    await insert_orders(user.id, 0, 6)
    current = service(monkeypatch)
    seen = []
    for _ in range(3):
        rows = await current.poll_pending_transactions(limit=5)
        assert len({row["order_id"] for row in rows}) == len(rows) == 5
        seen.extend(row["order_id"] for row in rows if row.get("scan_lane") == "history")
    assert seen == ["freekassa-0", "freekassa-1", "freekassa-0"]
    assert await current.poll_pending_transactions(limit=0) == []


@pytest.mark.asyncio
async def test_unverified_history_never_settles_and_one_off_does_not_move_cursor(monkeypatch):
    user = await database.get_or_create_user(12345)
    await insert_orders(user.id, 0, 6)
    current = service(monkeypatch)

    async def wrong_payment(**kwargs):
        return {"merchant_order_id": kwargs["merchant_order_id"], "paid": True,
                "amount": "99.00", "currency": "RUB", "status": "paid"}

    async def complete(_order_id):
        raise AssertionError("unverified payment must not be settled")

    monkeypatch.setattr(current, "get_payment", wrong_payment)
    first = await current.poll_pending_transactions(limit=5, complete_order=complete)
    assert all(row["action"] == "verification_failed" for row in first)
    await current.poll_pending_transactions(limit=5, rotate_history=False, complete_order=complete)
    second = await current.poll_pending_transactions(limit=5, complete_order=complete)
    assert [r["order_id"] for r in second if r.get("scan_lane") == "history"] == ["freekassa-1"]

@pytest.mark.asyncio
async def test_cursor_schema_uses_native_ddl_on_postgres(monkeypatch):
    from unittest.mock import AsyncMock

    class PgConnection:
        def __init__(self):
            self.execute = AsyncMock(side_effect=AssertionError("generic CREATE is skipped"))
            self.execute_native_ddl = AsyncMock()

    monkeypatch.setattr(database.db_backend, "is_postgres", lambda: True)
    connection = PgConnection()
    await database._ensure_freekassa_reconcile_schema(connection)
    connection.execute.assert_not_awaited()
    connection.execute_native_ddl.assert_awaited_once()
    statement = connection.execute_native_ddl.await_args.args[0]
    assert "CREATE TABLE IF NOT EXISTS freekassa_reconcile_cursor" in statement

