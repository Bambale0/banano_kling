from __future__ import annotations

import pytest

from bot.handlers.lava_checkout import (
    LAVA_CHECKOUT_FOREIGN,
    LAVA_CHECKOUT_RUB,
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
        ("buy_lava_rub_start", (LAVA_CHECKOUT_RUB, "start")),
        ("buy_lava_sbp_start", (LAVA_CHECKOUT_RUB, "start")),
        ("buy_lava_card_optimal", (LAVA_CHECKOUT_RUB, "optimal")),
        ("buy_lava_pro", (LAVA_CHECKOUT_RUB, "pro")),
        ("buy_lava_foreign_pro", (LAVA_CHECKOUT_FOREIGN, "pro")),
    ],
)
def test_lava_callbacks_route_rub_legacy_buttons_to_unified_checkout(
    callback_data, expected
):
    assert parse_lava_checkout_callback(callback_data) == expected


def test_payment_menu_shows_one_lava_rub_checkout() -> None:
    keyboard = _payment_options_keyboard(
        "studio",
        stars=True,
        lava_rub=True,
        lava_foreign=False,
        lava_foreign_price_usd=None,
        crypto=True,
        freekassa=False,
    )
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    labels = [button.text for button in buttons]
    callbacks = [button.callback_data for button in buttons if button.callback_data]

    assert labels == [
        "💳 Lava — карта / СБП",
        "⭐ Stars",
        "₿ Криптовалюта",
        "◀️ Назад",
    ]
    assert "buy_lava_rub_studio" in callbacks
    assert "buy_lava_card_studio" not in callbacks
    assert "buy_lava_sbp_studio" not in callbacks


def test_payment_menu_can_show_foreign_lava_checkout_separately() -> None:
    keyboard = _payment_options_keyboard(
        "pro",
        stars=False,
        lava_rub=True,
        lava_foreign=True,
        lava_foreign_price_usd=15.4,
        crypto=False,
        freekassa=False,
    )
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    labels = [button.text for button in buttons]
    callbacks = [button.callback_data for button in buttons if button.callback_data]

    assert labels == [
        "💳 Lava — карта / СБП",
        "🌍 USD · $15.4",
        "◀️ Назад",
    ]
    assert "buy_lava_rub_pro" in callbacks
    assert "buy_lava_foreign_pro" in callbacks


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
async def test_lava_invoice_payload_can_use_explicit_sbp_for_legacy_integrations(monkeypatch):
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
async def test_lava_invoice_payload_can_use_card_for_legacy_integrations(monkeypatch):
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


@pytest.mark.asyncio
async def test_unified_lava_invoice_omits_provider_and_method(monkeypatch):
    service = LavaService(api_key="test-key")
    captured = {}

    async def fake_request(method, path, payload=None, params=None):
        captured["payload"] = payload
        return {
            "ok": True,
            "id": "invoice-unified-1",
            "paymentUrl": "https://pay.example/invoice-unified-1",
        }

    monkeypatch.setattr(service, "_request", fake_request)

    result = await service.create_invoice(
        email="customer2026@gmail.com",
        offer_id="offer-rub-1",
        currency="RUB",
        buyer_language="RU",
        client_utm={"telegram_id": "123", "payment_mode": "rub"},
    )

    assert result["ok"] is True
    assert captured["payload"]["currency"] == "RUB"
    assert "paymentProvider" not in captured["payload"]
    assert "paymentMethod" not in captured["payload"]
