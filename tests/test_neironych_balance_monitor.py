from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from bot.services.neironych_balance_monitor import (
    BalanceAlertSettings,
    BalanceMonitor,
    parse_balance_rub,
)


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}

    async def set(self, key, value, *, ex, nx):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    async def delete(self, key):
        return int(self.data.pop(key, None) is not None)

    async def eval(self, script, count, key, token):
        del script, count
        if self.data.get(key) == token:
            return await self.delete(key)
        return 0


class FakeCache:
    def __init__(self, client=None):
        self.client = client

    async def get_client(self):
        return self.client

    def build_key(self, suffix):
        return "test:" + suffix


def settings(*, admins=(10,), threshold="2000"):
    return BalanceAlertSettings(
        api_key="test-key",
        base_url="https://api.example.test",
        admin_ids=admins,
        threshold_rub=Decimal(threshold),
        interval_seconds=900,
        reminder_seconds=43200,
        timeout_seconds=5,
    )


def test_balance_uses_cash_not_credit_limit():
    payload = {"balance_rub": "1999.99", "available_balance_rub": "9500.00"}
    assert parse_balance_rub(payload) == Decimal("1999.99")


@pytest.mark.parametrize(
    "payload",
    [
        None, [], {}, {"balance_rub": None}, {"balance_rub": 100},
        {"balance_rub": True}, {"balance_rub": ""}, {"balance_rub": "NaN"},
        {"balance_rub": "Infinity"}, {"balance_rub": "not-money"},
    ],
)
def test_invalid_balance_fails_closed(payload):
    with pytest.raises((ValueError, TypeError)):
        parse_balance_rub(payload)


@pytest.mark.asyncio
async def test_low_balance_alerts_once_and_resets_after_topup(monkeypatch):
    bot = AsyncMock()
    cache = FakeCache(FakeRedis())
    monitor = BalanceMonitor(bot, settings(), cache=cache)
    monkeypatch.setattr(
        monitor,
        "fetch_balance",
        AsyncMock(side_effect=[
            Decimal("1999.99"), Decimal(1100), Decimal(2000), Decimal(1999),
        ]),
    )

    await monitor.check_once()
    await monitor.check_once()
    assert bot.send_message.await_count == 1
    assert "1 999,99 ₽" in bot.send_message.await_args.kwargs["text"]

    await monitor.check_once()  # threshold itself is healthy
    await monitor.check_once()
    assert bot.send_message.await_count == 2


@pytest.mark.asyncio
async def test_concurrent_checks_alert_each_admin_once(monkeypatch):
    bot = AsyncMock()
    monitor = BalanceMonitor(bot, settings(admins=(10, 20)), cache=FakeCache(FakeRedis()))
    monkeypatch.setattr(monitor, "fetch_balance", AsyncMock(return_value=Decimal(50)))

    await asyncio.gather(*(monitor.check_once() for _ in range(10)))

    assert bot.send_message.await_count == 2
    assert {call.kwargs["chat_id"] for call in bot.send_message.await_args_list} == {10, 20}


@pytest.mark.asyncio
async def test_unavailable_redis_does_not_spam_admin(monkeypatch):
    bot = AsyncMock()
    monitor = BalanceMonitor(bot, settings(), cache=FakeCache())
    monkeypatch.setattr(monitor, "fetch_balance", AsyncMock(return_value=Decimal(1000)))

    await monitor.check_once()

    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_telegram_send_releases_claim_for_retry(monkeypatch):
    bot = AsyncMock()
    bot.send_message.side_effect = [RuntimeError("transport error"), None]
    cache = FakeCache(FakeRedis())
    monitor = BalanceMonitor(bot, settings(), cache=cache)
    monkeypatch.setattr(monitor, "fetch_balance", AsyncMock(return_value=Decimal(1000)))

    await monitor.check_once()
    await monitor.check_once()

    assert bot.send_message.await_count == 2


@pytest.mark.asyncio
async def test_failed_or_unparseable_api_check_never_sends(monkeypatch):
    bot = AsyncMock()
    monitor = BalanceMonitor(bot, settings(), cache=FakeCache(FakeRedis()))
    monkeypatch.setattr(monitor, "fetch_balance", AsyncMock(side_effect=ValueError("invalid balance")))

    with pytest.raises(ValueError):
        await monitor.check_once()
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_get_uses_authenticated_endpoint(monkeypatch):
    calls = []

    class Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def json(self, **_):
            return {"balance_rub": "2200.55", "available_balance_rub": "9000.00"}

    class Session:
        def __init__(self, *, timeout):
            assert timeout.total == 5

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        def get(self, url, *, headers, allow_redirects):
            calls.append((url, headers, allow_redirects))
            return Response()

    from bot.services import neironych_balance_monitor as module

    monkeypatch.setattr(module.aiohttp, "ClientSession", Session)
    monitor = BalanceMonitor(AsyncMock(), settings(), cache=FakeCache(FakeRedis()))
    assert await monitor.fetch_balance() == Decimal("2200.55")
    assert calls == [(
        "https://api.example.test/v1/balance",
        {"Authorization": "Bearer test-key", "Accept": "application/json"},
        False,
    )]
