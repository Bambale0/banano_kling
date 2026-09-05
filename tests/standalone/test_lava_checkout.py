from __future__ import annotations

import pytest

from bot.handlers.lava_checkout import (
    LAVA_CHECKOUT_CARD,
    LAVA_CHECKOUT_FOREIGN,
    LAVA_CHECKOUT_FOREIGN_CARD,
    LAVA_CHECKOUT_FOREIGN_PAYPAL,
    LAVA_CHECKOUT_SBP,
    LAVA_RUB_CARD_PAYMENT_METHOD,
    LAVA_RUB_PAYMENT_METHOD,
    LAVA_RUB_PAYMENT_PROVIDER,
    _payment_options_keyboard,
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
        ("mailto:user2026@gmail.com", "user2026@gmail.com"),
        ("User 2026 <user2026@gmail.com>", "user2026@gmail.com"),
        ("user2026\u200b@gmail.com", "user2026@gmail.com"),
    ],
)
def test_lava_email_accepts_real_customer_addresses(raw, expected):
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
        ("buy_lava_foreign_pro", (LAVA_CHECKOUT_FOREIGN, "pro")),
        (
            "buy_lava_foreign_card_pro",
            (LAVA_CHECKOUT_FOREIGN_CARD, "pro"),
        ),
        (
            "buy_lava_foreign_paypal_pro",
            (LAVA_CHECKOUT_FOREIGN_PAYPAL, "pro"),
        ),
    ],
)
def test_lava_callbacks_keep_explicit_payment_methods(callback_data, expected):
    assert parse_lava_checkout_callback(callback_data) == expected


def test_payment_menu_shows_card_and_sbp_separately() -> None:
    keyboard = _payment_options_keyboard(
        "studio",
        stars=True,
        lava_card=True,
        lava_sbp=True,
        lava_foreign=False,
        lava_foreign_price_usd=None,
        crypto=True,
        freekassa=False,
    )
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    labels = [button.text for button in buttons]
    callbacks = [button.callback_data for button in buttons if button.callback_data]

    assert labels == [
        "💳 Картой",
        "⚡ СБП",
        "СНГ И ЗАРУБЕЖНЫЕ",
        "₿ Криптовалюта",
        "⭐ Stars",
        "◀️ Назад",
    ]
    assert "buy_lava_card_studio" in callbacks
    assert "buy_lava_sbp_studio" in callbacks


def test_payment_menu_shows_foreign_card_and_paypal_separately() -> None:
    keyboard = _payment_options_keyboard(
        "pro",
        stars=False,
        lava_card=True,
        lava_sbp=True,
        lava_foreign=True,
        lava_foreign_price_usd=15.4,
        crypto=False,
        freekassa=False,
    )
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    labels = [button.text for button in buttons]
    callbacks = [button.callback_data for button in buttons if button.callback_data]

    assert labels == [
        "💳 Картой",
        "⚡ СБП",
        "СНГ И ЗАРУБЕЖНЫЕ",
        "🌍 Зарубежная карта",
        "🌍 PayPal",
        "◀️ Назад",
    ]
    assert "buy_lava_foreign_card_pro" in callbacks
    assert "buy_lava_foreign_paypal_pro" in callbacks


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

    assert result["code"] == "invalid_customer_email"
    assert called is False


@pytest.mark.asyncio
async def test_lava_invoice_payload_uses_explicit_sbp(monkeypatch):
    service = LavaService(api_key="test-key")
    captured = {}

    async def fake_request(method, path, payload=None, params=None):
        captured.update({"method": method, "path": path, "payload": payload})
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
    assert captured["payload"]["paymentProvider"] == "PAY2ME"
    assert captured["payload"]["paymentMethod"] == "SBP"


@pytest.mark.asyncio
async def test_lava_invoice_payload_uses_explicit_card(monkeypatch):
    service = LavaService(api_key="test-key")
    captured = {}

    async def fake_request(method, path, payload=None, params=None):
        captured["payload"] = payload
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
    )

    assert result["ok"] is True
    assert captured["payload"]["paymentMethod"] == "CARD"
