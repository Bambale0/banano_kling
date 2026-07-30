from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace

from bot import config as config_module
from bot import internal_api
from bot.handlers import freekassa_payments
from bot.services import freekassa_service as freekassa_module
from bot.services import yookassa_service as legacy_payment_module


def _configured_service(monkeypatch) -> freekassa_module.FreeKassaService:
    monkeypatch.setenv("FREEKASSA_MERCHANT_ID", "7012")
    monkeypatch.setenv("FREEKASSA_SECRET_WORD", "secret")
    monkeypatch.setenv("FREEKASSA_SECRET_WORD_2", "secret2")
    monkeypatch.setenv("FREEKASSA_API_KEY", "api-key")
    monkeypatch.setenv("FREEKASSA_CURRENCY", "RUB")
    monkeypatch.setenv("FREEKASSA_VERIFY_IP", "1")
    return freekassa_module.FreeKassaService()


def test_integration_modules_import_and_legacy_alias_is_freekassa_only():
    assert freekassa_payments.router is not None
    assert callable(freekassa_payments.handle_freekassa_webhook)
    assert callable(freekassa_payments.setup_freekassa_routes)
    assert callable(freekassa_payments.handle_freekassa_success_return)
    assert callable(freekassa_payments.handle_freekassa_fail_return)
    assert (
        legacy_payment_module.yookassa_service.__class__.__name__
        == "FreeKassaLegacyAliasService"
    )


def test_freekassa_return_pages_are_domain_safe():
    success = asyncio.run(freekassa_payments.handle_freekassa_success_return(None))
    failure = asyncio.run(freekassa_payments.handle_freekassa_fail_return(None))

    assert success.status == 200
    assert failure.status == 200
    assert "Оплата принята" in success.text
    assert "Оплата не завершена" in failure.text
    assert "https://t.me/Neuromixx_bot" in success.text
    assert "https://t.me/Neuromixx_bot" in failure.text


def test_legacy_yookassa_webhooks_are_retired():
    async def unexpected_handler(_request):
        raise AssertionError("retired YooKassa handler must never run")

    for path in ("/yookassa/webhook", "/webhook/yookassa"):
        request = SimpleNamespace(path=path)
        response = asyncio.run(
            internal_api.internal_auth_middleware(request, unexpected_handler)
        )
        payload = json.loads(response.text)

        assert response.status == 410
        assert payload == {
            "error": "payment_provider_removed",
            "provider": "lava",
            "webhook": "/lava/webhook",
        }


def test_config_defaults_to_freekassa_when_configured():
    cfg = config_module.Config()
    cfg.PAYMENT_PROVIDER = "freekassa"
    cfg.FREEKASSA_MERCHANT_ID = "7012"
    cfg.FREEKASSA_SECRET_WORD = "secret"
    cfg.FREEKASSA_SECRET_WORD_2 = "secret2"
    assert cfg.payment_provider == "freekassa"
    assert cfg.has_freekassa is True


def test_amount_is_stable_for_signatures():
    assert freekassa_module.normalize_amount(100) == "100.00"
    assert freekassa_module.normalize_amount("100.1") == "100.10"
    assert freekassa_module.normalize_amount("100.115") == "100.12"


def test_sci_signature_matches_documented_formula():
    actual = freekassa_module.build_sci_signature(
        "7012", "100.11", "secret", "RUB", "154"
    )
    expected = hashlib.md5(
        b"7012:100.11:secret:RUB:154", usedforsecurity=False
    ).hexdigest()
    assert actual == expected


def test_notification_signature_uses_raw_provider_amount():
    actual = freekassa_module.build_notification_signature(
        "7012", "100.00", "secret2", "154"
    )
    expected = hashlib.md5(
        b"7012:100.00:secret2:154", usedforsecurity=False
    ).hexdigest()
    assert actual == expected


def test_api_signature_sorts_fields_before_hmac():
    payload = {"paymentId": "order-1", "nonce": 123, "shopId": 7012}
    actual = freekassa_module.build_api_signature(payload, "api-key")
    expected = hmac.new(
        b"api-key",
        b"123|order-1|7012",
        hashlib.sha256,
    ).hexdigest()
    assert actual == expected


def test_api_checkout_sends_required_card_fields(monkeypatch):
    service = _configured_service(monkeypatch)
    captured = {}

    async def fake_api_post(endpoint, payload):
        captured.update(endpoint=endpoint, payload=payload)
        return {"type": "success", "orderId": 123, "location": "https://pay.example/order"}

    monkeypatch.setattr(service, "_api_post", fake_api_post)
    result = asyncio.run(service.create_payment(
        amount_rub=100,
        order_id="order-1",
        email="buyer@example.com",
        customer_ip="203.0.113.7",
        payment_system_id=freekassa_module.FREEKASSA_CARD_RUB_METHOD_ID,
    ))

    assert result["ok"] is True
    assert result["mode"] == "api"
    assert result["payment_url"] == "https://pay.example/order"
    assert captured == {"endpoint": "orders/create", "payload": {
        "paymentId": "order-1", "i": 36, "email": "buyer@example.com",
        "ip": "203.0.113.7", "amount": "100.00", "currency": "RUB",
    }}


def test_api_checkout_requires_real_email_and_ip(monkeypatch):
    service = _configured_service(monkeypatch)
    result = asyncio.run(service.create_payment(
        amount_rub=100, order_id="order-1",
        payment_system_id=freekassa_module.FREEKASSA_SBP_METHOD_ID,
    ))
    assert result == {"ok": False, "error": "Customer email and IP are required"}


def test_notification_verification_checks_shop_and_signature(monkeypatch):
    service = _configured_service(monkeypatch)
    payload = {
        "MERCHANT_ID": "7012",
        "AMOUNT": "100.00",
        "MERCHANT_ORDER_ID": "order-1",
        "SIGN": freekassa_module.build_notification_signature(
            "7012", "100.00", "secret2", "order-1"
        ),
    }

    assert service.verify_notification(payload) == (True, "ok")

    payload["AMOUNT"] = "101.00"
    assert service.verify_notification(payload) == (False, "invalid_signature")


def test_webhook_ip_allowlist_defaults_to_documented_addresses(monkeypatch):
    service = _configured_service(monkeypatch)
    assert service.is_allowed_webhook_ip("168.119.157.136") is True
    assert service.is_allowed_webhook_ip("127.0.0.1") is False


def test_order_status_mapping():
    assert freekassa_module.normalize_order_status(0) == {
        "status_code": 0,
        "status": "new",
        "paid": False,
        "failed": False,
    }
    assert freekassa_module.normalize_order_status(1)["paid"] is True
    assert freekassa_module.normalize_order_status(6)["failed"] is True
    assert freekassa_module.normalize_order_status(8)["failed"] is True
    assert freekassa_module.normalize_order_status(9)["failed"] is True
