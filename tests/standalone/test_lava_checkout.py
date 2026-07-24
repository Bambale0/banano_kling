from __future__ import annotations

import pytest

from bot.handlers.lava_checkout import (
    LAVA_RUB_PAYMENT_METHOD,
    LAVA_RUB_PAYMENT_PROVIDER,
    normalize_lava_customer_email,
)
from bot.services.lava_service import LavaService


def test_lava_email_accepts_real_customer_address():
    assert normalize_lava_customer_email(" User.Name+pay@gmail.com ") == (
        "user.name+pay@gmail.com"
    )


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
    ],
)
def test_lava_email_rejects_placeholders_and_invalid_values(value):
    assert normalize_lava_customer_email(value) is None


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
        email="customer@gmail.com",
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
        "email": "customer@gmail.com",
        "offerId": "offer-1",
        "currency": "RUB",
        "paymentProvider": "PAY2ME",
        "paymentMethod": "SBP",
        "buyerLanguage": "RU",
        "clientUtm": {"telegram_id": "123"},
    }
