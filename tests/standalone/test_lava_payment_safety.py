from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.services import lava_payment_safety as safety


class FakeRequest:
    def __init__(self, body: bytes, *, headers: dict[str, str] | None = None):
        self._body = body
        self.headers = headers or {"X-Real-IP": "158.160.60.174"}
        self.remote = "127.0.0.1"
        self.app = {"bot": None}

    async def read(self) -> bytes:
        return self._body


def _extract_first(payload, keys):
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return value
        for value in payload.values():
            found = _extract_first(value, keys)
            if found not in (None, ""):
                return found
    return None


def _payments_module(complete_result):
    async def complete_transaction(order_id, bot=None):
        return complete_result

    return SimpleNamespace(
        _extract_first=_extract_first,
        _complete_transaction=complete_transaction,
        _build_promo_bonus_text=lambda value: "",
        _build_bonus_text=lambda value: "",
        _notify_user=None,
    )


def _success_body() -> bytes:
    return (
        b'{"eventType":"payment.success","product":{"id":"product-1"},'
        b'"contractId":"contract-1","amount":500.0,"currency":"RUB",'
        b'"status":"completed","errorMessage":""}'
    )


def test_basic_authorization_decoder():
    assert safety._decode_basic_authorization("Basic dXNlcjpwYXNz") == "user:pass"
    assert safety._decode_basic_authorization("Bearer token") is None
    assert safety._decode_basic_authorization("Basic invalid!") is None


def test_invoice_item_extraction_supports_nested_pages():
    items = safety._extract_invoice_items(
        {"data": {"items": [{"id": "invoice-1"}, {"id": "invoice-2"}]}}
    )
    assert [item["id"] for item in items] == ["invoice-1", "invoice-2"]


def test_webhook_amount_and_currency_must_match_transaction(monkeypatch):
    transaction = SimpleNamespace(amount_rub=500)
    assert safety._payload_amount_matches(
        transaction,
        {"amount": 500.0, "currency": "RUB"},
    )
    assert not safety._payload_amount_matches(
        transaction,
        {"amount": 150.0, "currency": "RUB"},
    )
    assert not safety._payload_amount_matches(
        transaction,
        {"amount": 500.0, "currency": "USD"},
    )
    assert not safety._payload_amount_matches(
        transaction,
        {"amount": 500.0, "currency": "EUR"},
    )


def test_foreign_usd_webhook_matches_package_price_usd(monkeypatch):
    from bot.services import preset_manager as preset_manager_module

    transaction = SimpleNamespace(
        order_id="123456_1788214737781_pro",
        amount_rub=1087.0,
    )
    monkeypatch.setattr(
        preset_manager_module.preset_manager,
        "get_package",
        lambda package_id: (
            {"id": "pro", "price_rub": 1087.0, "price_usd": 15.0}
            if package_id == "pro"
            else None
        ),
    )

    # USD amount equal to the package price_usd is accepted.
    assert safety._payload_amount_matches(
        transaction,
        {"amount": 15.0, "currency": "USD"},
    )
    # A wrong USD amount is still rejected.
    assert not safety._payload_amount_matches(
        transaction,
        {"amount": 14.0, "currency": "USD"},
    )
    # Unknown package or malformed order id fails closed.
    assert not safety._payload_amount_matches(
        SimpleNamespace(order_id="123456_1788214737781_unknown", amount_rub=1.0),
        {"amount": 15.0, "currency": "USD"},
    )
    assert not safety._payload_amount_matches(
        SimpleNamespace(order_id="nonsense", amount_rub=1.0),
        {"amount": 15.0, "currency": "USD"},
    )


@pytest.mark.asyncio
async def test_success_webhook_returns_503_while_provider_is_in_progress(monkeypatch):
    transaction = SimpleNamespace(
        order_id="order-1",
        payment_id="contract-1",
        provider="lava",
        amount_rub=500.0,
        user_id=1,
    )

    async def lookup_transaction(**kwargs):
        return transaction

    async def provider_status(*args, **kwargs):
        return "in_progress", "invoice-1"

    monkeypatch.setattr(safety, "_lookup_lava_transaction", lookup_transaction)
    monkeypatch.setattr(safety, "_provider_status", provider_status)
    monkeypatch.setattr(safety, "_auth_configuration_present", lambda: False)

    response = await safety.safe_handle_lava_webhook(
        FakeRequest(_success_body()),
        payments_module=_payments_module({"ok": True}),
    )

    assert response.status == 503


@pytest.mark.asyncio
async def test_success_webhook_completes_only_after_provider_confirmation(monkeypatch):
    transaction = SimpleNamespace(
        order_id="order-1",
        payment_id="contract-1",
        provider="lava",
        amount_rub=500.0,
        credits=50,
        user_id=1,
    )
    completed_transaction = SimpleNamespace(
        order_id="order-1",
        amount_rub=500.0,
        credits=50,
        user_id=1,
    )
    completion = {
        "ok": True,
        "already_completed": False,
        "transaction": completed_transaction,
        "telegram_id": 123,
        "referral_bonus": {},
        "promo_bonus": {},
    }
    calls = []

    async def lookup_transaction(**kwargs):
        return transaction

    async def provider_status(*args, **kwargs):
        return "completed", "invoice-1"

    async def notify(*args, **kwargs):
        calls.append("notified")

    payments = _payments_module(completion)
    monkeypatch.setattr(safety, "_lookup_lava_transaction", lookup_transaction)
    monkeypatch.setattr(safety, "_provider_status", provider_status)
    monkeypatch.setattr(safety, "_notify_completed_payment", notify)
    monkeypatch.setattr(safety, "_auth_configuration_present", lambda: False)

    response = await safety.safe_handle_lava_webhook(
        FakeRequest(_success_body()),
        payments_module=payments,
    )

    assert response.status == 200
    assert calls == ["notified"]


@pytest.mark.asyncio
async def test_unknown_route_probe_is_ignored_without_authentication():
    request = FakeRequest(b'{"test":"tg-route-check"}', headers={"X-Real-IP": "127.0.0.1"})
    response = await safety.safe_handle_lava_webhook(
        request,
        payments_module=_payments_module({"ok": True}),
    )
    assert response.status == 200
