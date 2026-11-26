from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from bot.services import freekassa_service as module


def configured_service(monkeypatch):
    for key, value in {
        "FREEKASSA_MERCHANT_ID": "7012",
        "FREEKASSA_SECRET_WORD": "test-secret",
        "FREEKASSA_SECRET_WORD_2": "test-secret-2",
        "FREEKASSA_API_KEY": "test-key",
        "FREEKASSA_CURRENCY": "RUB",
    }.items():
        monkeypatch.setenv(key, value)
    return module.FreeKassaService()


@pytest.mark.parametrize("orders", [
    [{"merchant_order_id": "other", "status": 1}],
    [{"status": 1}],
    [
        {"merchant_order_id": "wanted", "status": 1},
        {"merchant_order_id": "wanted", "status": 9},
    ],
])
def test_lookup_rejects_unbound_or_ambiguous_orders(monkeypatch, orders):
    service = configured_service(monkeypatch)

    async def post(endpoint, payload):
        assert endpoint == "orders"
        assert payload == {"paymentId": "wanted"}
        return {"orders": orders}

    monkeypatch.setattr(service, "_api_post", post)
    assert asyncio.run(service.get_payment(merchant_order_id="wanted")) is None


def test_lookup_uses_exact_order_not_first_row(monkeypatch):
    service = configured_service(monkeypatch)

    async def post(_endpoint, _payload):
        return {"orders": [
            {"merchant_order_id": "other", "status": 9},
            {"merchant_order_id": "wanted", "status": 1,
             "amount": "100.00", "currency": "RUB"},
        ]}

    monkeypatch.setattr(service, "_api_post", post)
    result = asyncio.run(service.get_payment(merchant_order_id="wanted"))
    assert result["paid"] is True
    assert result["merchant_order_id"] == "wanted"


@pytest.mark.parametrize("amount,currency,expected", [
    ("100.00", "RUB", "completed"),
    ("99.00", "RUB", "verification_failed"),
    (None, "RUB", "verification_failed"),
    ("NaN", "RUB", "verification_failed"),
    ("100.00", "USD", "verification_failed"),
    ("100.00", None, "verification_failed"),
])
def test_poll_requires_verified_amount_and_currency(
    monkeypatch, amount, currency, expected
):
    service = configured_service(monkeypatch)
    completed = []

    class FakeConnection:
        row_factory = None

        async def execute(self, query, _params):
            assert query.startswith("SELECT ")

            async def fetchall():
                return [{"order_id": "wanted", "payment_id": "fk-1",
                         "amount_rub": 100}]
            return SimpleNamespace(fetchall=fetchall)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    async def payment(**_kwargs):
        return {"merchant_order_id": "wanted", "paid": True, "failed": False,
                "status": "paid", "amount": amount, "currency": currency}

    async def complete(order_id):
        completed.append(order_id)
        return {"ok": True}

    monkeypatch.setattr(module.db_backend, "connect", FakeConnection)
    monkeypatch.setattr(service, "get_payment", payment)
    results = asyncio.run(service.poll_pending_transactions(complete_order=complete, rotate_history=False))
    assert results[0]["action"] == expected
    assert completed == (["wanted"] if expected == "completed" else [])
