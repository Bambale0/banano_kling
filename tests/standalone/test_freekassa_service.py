from __future__ import annotations

import hashlib
import hmac
from urllib.parse import parse_qs, urlsplit

from bot.services.freekassa_service import (
    FreeKassaService,
    build_api_signature,
    build_notification_signature,
    build_sci_signature,
    normalize_amount,
    normalize_order_status,
)


def _configured_service(monkeypatch) -> FreeKassaService:
    monkeypatch.setenv("FREEKASSA_MERCHANT_ID", "7012")
    monkeypatch.setenv("FREEKASSA_SECRET_WORD", "secret")
    monkeypatch.setenv("FREEKASSA_SECRET_WORD_2", "secret2")
    monkeypatch.setenv("FREEKASSA_CURRENCY", "RUB")
    monkeypatch.setenv("FREEKASSA_VERIFY_IP", "1")
    return FreeKassaService()


def test_amount_is_stable_for_signatures():
    assert normalize_amount(100) == "100.00"
    assert normalize_amount("100.1") == "100.10"
    assert normalize_amount("100.115") == "100.12"


def test_sci_signature_matches_documented_formula():
    actual = build_sci_signature("7012", "100.11", "secret", "RUB", "154")
    expected = hashlib.md5(b"7012:100.11:secret:RUB:154").hexdigest()
    assert actual == expected


def test_notification_signature_uses_raw_provider_amount():
    actual = build_notification_signature("7012", "100.00", "secret2", "154")
    expected = hashlib.md5(b"7012:100.00:secret2:154").hexdigest()
    assert actual == expected


def test_api_signature_sorts_fields_before_hmac():
    payload = {"paymentId": "order-1", "nonce": 123, "shopId": 7012}
    actual = build_api_signature(payload, "api-key")
    expected = hmac.new(
        b"api-key",
        b"123|order-1|7012",
        hashlib.sha256,
    ).hexdigest()
    assert actual == expected


def test_checkout_url_contains_signed_required_fields(monkeypatch):
    service = _configured_service(monkeypatch)
    url = service.create_payment_url(amount_rub=100, order_id="order-1")
    query = parse_qs(urlsplit(url).query)

    assert query["m"] == ["7012"]
    assert query["oa"] == ["100.00"]
    assert query["currency"] == ["RUB"]
    assert query["o"] == ["order-1"]
    assert query["lang"] == ["ru"]
    assert query["s"] == [
        build_sci_signature("7012", "100.00", "secret", "RUB", "order-1")
    ]


def test_notification_verification_checks_shop_and_signature(monkeypatch):
    service = _configured_service(monkeypatch)
    payload = {
        "MERCHANT_ID": "7012",
        "AMOUNT": "100.00",
        "MERCHANT_ORDER_ID": "order-1",
        "SIGN": build_notification_signature(
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
    assert normalize_order_status(0) == {
        "status_code": 0,
        "status": "new",
        "paid": False,
        "failed": False,
    }
    assert normalize_order_status(1)["paid"] is True
    assert normalize_order_status(6)["failed"] is True
    assert normalize_order_status(8)["failed"] is True
    assert normalize_order_status(9)["failed"] is True
