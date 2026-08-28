from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.handlers.lava_checkout import (
    LAVA_CHECKOUT_CARD,
    LAVA_CHECKOUT_SBP,
    LAVA_RUB_CARD_PAYMENT_METHOD,
    LAVA_RUB_PAYMENT_METHOD,
    LAVA_RUB_PAYMENT_PROVIDER,
    _payment_options_keyboard,
    handle_lava_checkout_entry,
    normalize_lava_customer_email,
    parse_lava_checkout_callback,
)
from bot.services.lava_service import LavaService


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" User.Name+pay@gmail.com ", "user.name+pay@gmail.com"),
        ("name123@gmail.com", "name123@gmail.com"),
        ("123name@mail.ru", "123name@mail.ru"),
        ("user2026@ya.ru", "user2026@ya.ru"),
        ("user1@domain2026.ru", "user1@domain2026.ru"),
        ("mailto:user2026@gmail.com", "user2026@gmail.com"),
        ("User 2026 <user2026@gmail.com>", "user2026@gmail.com"),
        ("user2026\u200b@gmail.com", "user2026@gmail.com"),
    ],
)
def test_lava_email_accepts_real_customer_addresses_with_digits(raw, expected):
    assert normalize_lava_customer_email(raw) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-an-email",
        "buyer@example.com",
        "client@example.com",
        "test@example.com",
        "customer@localhost",
        "customer@domain.invalid",
        ".customer@gmail.com",
        "customer.@gmail.com",
        "customer..name@gmail.com",
        "customer@-gmail.com",
    ],
)
def test_lava_email_rejects_placeholders_and_invalid_values(value):
    assert normalize_lava_customer_email(value) is None


@pytest.mark.parametrize(
    ("callback_data", "expected"),
    [
        ("buy_lava_sbp_start", (LAVA_CHECKOUT_SBP, "start")),
        ("buy_lava_card_optimal", (LAVA_CHECKOUT_CARD, "optimal")),
        ("buy_lava_pro", (LAVA_CHECKOUT_SBP, "pro")),
    ],
)
def test_lava_callbacks_support_direct_methods_and_legacy_buttons(
    callback_data, expected
):
    assert parse_lava_checkout_callback(callback_data) == expected


def test_payment_menu_routes_card_to_lava_and_sbp_to_freekassa():
    keyboard = _payment_options_keyboard(
        "studio",
        stars=True,
        lava_card=True,
        freekassa_sbp=True,
        crypto=True,
        freekassa=False,
    )
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    labels = [button.text for button in buttons]
    callbacks = [button.callback_data for button in buttons if button.callback_data]

    assert labels == [
        "💳 Картой",
        "⚡ СБП",
        "⭐ Stars",
        "₿ Криптовалюта",
        "◀️ Назад",
    ]
    assert "buy_lava_card_studio" in callbacks
    assert "freekassa_sbp_studio" in callbacks
    assert "buy_lava_sbp_studio" not in callbacks
    assert not any(
        provider in label.lower()
        for label in labels
        for provider in ("lava", "freekassa", "cryptobot")
    )


def test_payment_menu_does_not_restore_lava_sbp_when_freekassa_api_is_off():
    keyboard = _payment_options_keyboard(
        "studio",
        stars=False,
        lava_card=True,
        freekassa_sbp=False,
        crypto=False,
        freekassa=False,
    )
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    labels = [button.text for button in buttons]
    callbacks = [button.callback_data for button in buttons if button.callback_data]

    assert labels == ["💳 Картой", "◀️ Назад"]
    assert "buy_lava_card_studio" in callbacks
    assert not any("sbp" in callback for callback in callbacks)


def test_payment_menu_lists_freekassa_reserve_separately_from_direct_sbp():
    keyboard = _payment_options_keyboard(
        "start",
        stars=True,
        lava_card=True,
        freekassa_sbp=True,
        crypto=False,
        freekassa=True,
    )
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    callbacks = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    ]

    assert labels == [
        "🇷🇺 РФ — KASSA (резерв)",
        "💳 Картой",
        "⚡ СБП",
        "⭐ Stars",
        "◀️ Назад",
    ]
    assert "buy_freekassa_start" in callbacks
    assert "freekassa_sbp_start" in callbacks
    assert "buy_lava_sbp_start" not in callbacks


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("legacy_callback", "expected_package"),
    [
        ("buy_lava_sbp_start", "start"),
        ("buy_lava_pro", "pro"),
    ],
)
async def test_legacy_lava_sbp_buttons_are_migrated_to_freekassa(
    monkeypatch, legacy_callback, expected_package
):
    from bot.handlers import freekassa_payments, lava_checkout

    routed = {}

    async def fake_initiate(callback, state):
        routed["data"] = callback.data
        routed["state"] = state

    monkeypatch.setattr(
        freekassa_payments,
        "initiate_freekassa_payment",
        fake_initiate,
    )
    monkeypatch.setattr(lava_checkout.freekassa_service, "api_enabled", True)

    callback = SimpleNamespace(data=legacy_callback)
    state = object()
    await handle_lava_checkout_entry(callback, state)

    assert routed == {
        "data": f"freekassa_sbp_{expected_package}",
        "state": state,
    }


@pytest.mark.asyncio
async def test_lava_service_rejects_placeholder_email_before_api_call(monkeypatch):
    service = LavaService(api_key="test-key")
    called = False

    async def fake_request(method, path, payload=None, params=None):
        nonlocal called
        called = True
        return {"ok": True}

    monkeypatch.setattr(service, "_request", fake_request)

    result = await service.create_invoice(
        email="buyer@example.com",
        offer_id="offer-1",
        currency="RUB",
        payment_provider=LAVA_RUB_PAYMENT_PROVIDER,
        payment_method=LAVA_RUB_PAYMENT_METHOD,
    )

    assert result == {
        "ok": False,
        "status": 400,
        "code": "invalid_customer_email",
        "error": "Для оплаты Lava требуется реальная почта покупателя",
    }
    assert called is False


@pytest.mark.asyncio
async def test_lava_invoice_payload_uses_real_email_rub_and_sbp(monkeypatch):
    service = LavaService(api_key="test-key")
    captured = {}

    async def fake_request(method, path, payload=None, params=None):
        captured.update(
            {
                "method": method,
                "path": path,
                "payload": payload,
                "params": params,
            }
        )
        return {
            "ok": True,
            "id": "invoice-1",
            "paymentUrl": "https://pay.example/invoice-1",
        }

    monkeypatch.setattr(service, "_request", fake_request)

    result = await service.create_invoice(
        email="customer2026@gmail.com",
        offer_id="offer-1",
        currency="RUB",
        payment_provider=LAVA_RUB_PAYMENT_PROVIDER,
        payment_method=LAVA_RUB_PAYMENT_METHOD,
        buyer_language="RU",
        client_utm={"telegram_id": "123"},
    )

    assert result["ok"] is True
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v3/invoice"
    assert captured["payload"] == {
        "email": "customer2026@gmail.com",
        "offerId": "offer-1",
        "currency": "RUB",
        "paymentProvider": "PAY2ME",
        "paymentMethod": "SBP",
        "buyerLanguage": "RU",
        "clientUtm": {"telegram_id": "123"},
    }


@pytest.mark.asyncio
async def test_lava_invoice_payload_uses_card_method(monkeypatch):
    service = LavaService(api_key="test-key")
    captured = {}

    async def fake_request(method, path, payload=None, params=None):
        captured.update(
            {
                "method": method,
                "path": path,
                "payload": payload,
                "params": params,
            }
        )
        return {
            "ok": True,
            "id": "invoice-card-1",
            "paymentUrl": "https://pay.example/invoice-card-1",
        }

    monkeypatch.setattr(service, "_request", fake_request)

    result = await service.create_invoice(
        email="customer2026@gmail.com",
        offer_id="offer-card-1",
        currency="RUB",
        payment_method=LAVA_RUB_CARD_PAYMENT_METHOD,
        buyer_language="RU",
        client_utm={"telegram_id": "123", "payment_mode": "card"},
    )

    assert result["ok"] is True
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v3/invoice"
    assert captured["payload"] == {
        "email": "customer2026@gmail.com",
        "offerId": "offer-card-1",
        "currency": "RUB",
        "paymentMethod": "CARD",
        "buyerLanguage": "RU",
        "clientUtm": {"telegram_id": "123", "payment_mode": "card"},
    }
    assert "paymentProvider" not in captured["payload"]
