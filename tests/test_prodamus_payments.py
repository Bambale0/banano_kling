from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from bot.handlers.prodamus_payments import (
    ProdamusConfigurationError,
    ProdamusPayloadError,
    _validate_success_payload,
    build_prodamus_payment_url,
    canonical_hmac_json,
    handle_prodamus_webhook,
    parse_prodamus_form,
    sign_prodamus_payload,
    verify_prodamus_signature,
)


def test_prodamus_hmac_matches_canonical_fixture() -> None:
    payload = {
        "urlNotification": "https://api.example.com/hook",
        "products": [{"quantity": "1", "price": "100.00", "name": "Bananas"}],
        "sys": "neuromix",
        "do": "pay",
    }

    assert canonical_hmac_json(payload) == (
        '{"do":"pay","products":[{"name":"Bananas","price":"100.00",'
        '"quantity":"1"}],"sys":"neuromix",'
        '"urlNotification":"https:\\/\\/api.example.com\\/hook"}'
    )
    assert sign_prodamus_payload(payload, "secret") == (
        "c1d9158f8e9374f04aa024cfb3646545a3e99b4dbf434ec5a813476d874cef0c"
    )


def test_prodamus_signature_is_order_independent_and_rejects_tampering() -> None:
    first = {
        "sys": "neuromix",
        "do": "pay",
        "products": [{"price": 100, "name": "A", "quantity": 1}],
    }
    second = {
        "products": [{"quantity": 1, "name": "A", "price": 100}],
        "do": "pay",
        "sys": "neuromix",
    }
    signature = sign_prodamus_payload(first, "key")

    assert signature == sign_prodamus_payload(second, "key")
    assert verify_prodamus_signature(second, signature, "key") is True
    second["products"][0]["price"] = 101
    assert verify_prodamus_signature(second, signature, "key") is False


def test_build_prodamus_payment_url_contains_signed_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRODAMUS_PAYFORM_URL", "https://neuromix.payform.ru/")
    monkeypatch.setenv("PRODAMUS_SECRET_KEY", "merchant-secret")
    monkeypatch.setenv("PRODAMUS_SYS", "neuromix_bot")
    monkeypatch.setenv("PRODAMUS_WEBHOOK_URL", "https://api.example.com/prodamus/webhook")

    payment_url = build_prodamus_payment_url(
        order_id="42_1000_mini",
        package_id="mini",
        package_name="Mini",
        credits=100,
        amount_rub=1000,
        telegram_id=42,
    )
    parsed = urlparse(payment_url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "neuromix.payform.ru"
    assert query["do"] == ["pay"]
    assert query["sys"] == ["neuromix_bot"]
    assert query["callbackType"] == ["json"]
    assert query["payments_limit"] == ["1"]
    assert query["order_id"] == ["42_1000_mini"]
    assert query["products[0][sku]"] == ["mini"]
    assert query["products[0][price]"] == ["1000.00"]
    assert query["products[0][quantity]"] == ["1"]
    assert query["_param_telegram_id"] == ["42"]
    assert query["urlNotification"] == ["https://api.example.com/prodamus/webhook"]
    assert query["signature"][0]
    assert "merchant-secret" not in payment_url


def test_build_prodamus_payment_url_strips_non_bmp_emoji_from_product_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRODAMUS_PAYFORM_URL", "https://neuromix.payform.ru/")
    monkeypatch.setenv("PRODAMUS_SECRET_KEY", "merchant-secret")
    monkeypatch.setenv("PRODAMUS_SYS", "neuromixonlytm")

    payment_url = build_prodamus_payment_url(
        order_id="42_1000_start",
        package_id="start",
        package_name="🍌 Старт",
        credits=25,
        amount_rub=250,
        telegram_id=42,
    )
    query = parse_qs(urlparse(payment_url).query)

    assert query["products[0][name]"] == ["Старт — 25 бананов"]
    assert "🍌" not in query["products[0][name]"][0]


def test_build_prodamus_payment_url_rejects_public_payment_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "PRODAMUS_PAYFORM_URL",
        "https://link.payform.ru/?paymentLinkId=b0db3b6d-60ed-4e89-af0c-8ff58088c4b3",
    )
    monkeypatch.setenv("PRODAMUS_SECRET_KEY", "merchant-secret")
    monkeypatch.setenv("PRODAMUS_SYS", "neuromix_bot")

    with pytest.raises(ProdamusConfigurationError, match="merchant payment-page URL"):
        build_prodamus_payment_url(
            order_id="1",
            package_id="mini",
            package_name="Mini",
            credits=15,
            amount_rub=150,
            telegram_id=42,
        )


def test_build_prodamus_payment_url_requires_sys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRODAMUS_PAYFORM_URL", "https://neuromix.payform.ru/")
    monkeypatch.setenv("PRODAMUS_SECRET_KEY", "merchant-secret")
    monkeypatch.delenv("PRODAMUS_SYS", raising=False)

    with pytest.raises(ProdamusConfigurationError, match="PRODAMUS_SYS"):
        build_prodamus_payment_url(
            order_id="1",
            package_id="mini",
            package_name="Mini",
            credits=100,
            amount_rub=1000,
            telegram_id=42,
        )


def test_parse_prodamus_form_reconstructs_nested_products() -> None:
    payload = parse_prodamus_form(
        [
            ("payment_status", "success"),
            ("order_num", "42_1000_mini"),
            ("products[0][name]", "Mini"),
            ("products[0][price]", "1000.00"),
            ("products[0][quantity]", "1"),
        ]
    )

    assert payload == {
        "payment_status": "success",
        "order_num": "42_1000_mini",
        "products": [{"name": "Mini", "price": "1000.00", "quantity": "1"}],
    }


def test_success_payload_checks_amount_and_currency() -> None:
    transaction = SimpleNamespace(amount_rub=1000.0)

    _validate_success_payload(
        {"payment_status": "success", "sum": "1000.00", "currency": "rub"},
        transaction,
    )

    with pytest.raises(ProdamusPayloadError, match="amount mismatch"):
        _validate_success_payload(
            {"payment_status": "success", "sum": "999.00", "currency": "rub"},
            transaction,
        )

    with pytest.raises(ProdamusPayloadError, match="currency mismatch"):
        _validate_success_payload(
            {"payment_status": "success", "sum": "1000.00", "currency": "usd"},
            transaction,
        )


@pytest.mark.asyncio
async def test_prodamus_webhook_completes_valid_signed_payment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bot.handlers.prodamus_payments as prodamus
    from bot.handlers import payments as payments_handler

    payload = {
        "payment_status": "success",
        "order_num": "42_1000_mini",
        "order_id": "provider-order-777",
        "sum": "1000.00",
        "currency": "rub",
    }
    secret = "webhook-secret"
    signature = sign_prodamus_payload(payload, secret)
    monkeypatch.setenv("PRODAMUS_SECRET_KEY", secret)

    async def fake_transaction(order_id: str):
        assert order_id == "42_1000_mini"
        return SimpleNamespace(provider="prodamus", amount_rub=1000.0, status="pending")

    completed: list[str] = []

    async def fake_complete(order_id: str, *, bot=None):
        completed.append(order_id)
        return {"ok": True, "already_completed": False}

    monkeypatch.setattr(prodamus, "get_transaction_by_order", fake_transaction)
    monkeypatch.setattr(payments_handler, "_complete_transaction", fake_complete)

    class FakeRequest:
        content_type = "application/json"

        def __init__(self) -> None:
            self.headers = {"Sign": signature}
            self.app = {"bot": object()}

        async def json(self):
            return payload

    response = await handle_prodamus_webhook(FakeRequest())

    assert response.status == 200
    assert response.text == "success"
    assert completed == ["42_1000_mini"]


@pytest.mark.asyncio
async def test_prodamus_webhook_notifies_buyer_only_on_first_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bot.handlers.prodamus_payments as prodamus
    from bot.handlers import payments as payments_handler

    payload = {
        "payment_status": "success",
        "order_num": "42_2000_mini",
        "sum": "150.00",
        "currency": "rub",
    }
    secret = "webhook-secret"
    signature = sign_prodamus_payload(payload, secret)
    monkeypatch.setenv("PRODAMUS_SECRET_KEY", secret)

    async def fake_transaction(order_id: str):
        assert order_id == "42_2000_mini"
        return SimpleNamespace(provider="prodamus", amount_rub=150.0, status="pending")

    completion_count = 0

    async def fake_complete(order_id: str, *, bot=None):
        nonlocal completion_count
        completion_count += 1
        return {
            "ok": True,
            "already_completed": completion_count > 1,
            "telegram_id": 42,
            "transaction": SimpleNamespace(credits=15),
        }

    bot = SimpleNamespace(send_message=AsyncMock())
    monkeypatch.setattr(prodamus, "get_transaction_by_order", fake_transaction)
    monkeypatch.setattr(payments_handler, "_complete_transaction", fake_complete)

    class FakeRequest:
        content_type = "application/json"

        def __init__(self) -> None:
            self.headers = {"Sign": signature}
            self.app = {"bot": bot}

        async def json(self):
            return payload

    first = await handle_prodamus_webhook(FakeRequest())
    replay = await handle_prodamus_webhook(FakeRequest())

    assert first.status == 200
    assert replay.status == 200
    bot.send_message.assert_awaited_once_with(
        42,
        "✅ Оплата получена\nНачислено: 15 🍌",
    )


@pytest.mark.asyncio
async def test_prodamus_webhook_rejects_invalid_signature_before_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bot.handlers.prodamus_payments as prodamus

    payload = {
        "payment_status": "success",
        "order_num": "42_1000_mini",
        "sum": "1000.00",
    }
    monkeypatch.setenv("PRODAMUS_SECRET_KEY", "webhook-secret")

    async def should_not_query(_order_id: str):
        raise AssertionError("database must not be touched for invalid signatures")

    monkeypatch.setattr(prodamus, "get_transaction_by_order", should_not_query)

    class FakeRequest:
        content_type = "application/json"

        def __init__(self) -> None:
            self.headers = {"Sign": "deadbeef"}
            self.app = {"bot": None}

        async def json(self):
            return payload

    response = await handle_prodamus_webhook(FakeRequest())

    assert response.status == 401
    assert response.text == "error: invalid signature"


def test_default_prodamus_webhook_uses_tanyapi_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    import bot.handlers.prodamus_payments as prodamus

    monkeypatch.delenv("PRODAMUS_WEBHOOK_URL", raising=False)
    assert prodamus.DEFAULT_PRODAMUS_WEBHOOK_URL == "https://tanyapi.chillcreative.ru/prodamus/webhook"
    assert prodamus._webhook_url() == "https://tanyapi.chillcreative.ru/prodamus/webhook"
