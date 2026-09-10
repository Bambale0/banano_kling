from __future__ import annotations

import hashlib
from urllib.parse import parse_qs, urlparse

from bot.services import robokassa_service as robokassa_module


def _service(monkeypatch, *, test_mode: bool = False):
    monkeypatch.setenv("ROBOKASSA_MERCHANT_LOGIN", "demo-shop")
    monkeypatch.setenv("ROBOKASSA_PASSWORD1", "live-password-1")
    monkeypatch.setenv("ROBOKASSA_PASSWORD2", "live-password-2")
    monkeypatch.setenv("ROBOKASSA_HASH_ALGORITHM", "md5")
    monkeypatch.setenv("ROBOKASSA_TEST_MODE", "1" if test_mode else "0")
    return robokassa_module.RobokassaService()


def test_checkout_signature_matches_robokassa_formula():
    actual = robokassa_module.build_checkout_signature(
        "demo-shop", "299.00", "123456", "password-1"
    )
    expected = hashlib.md5(
        b"demo-shop:299.00:123456:password-1", usedforsecurity=False
    ).hexdigest()
    assert actual == expected


def test_result_signature_matches_robokassa_formula():
    actual = robokassa_module.build_result_signature(
        "299.000000", "123456", "password-2"
    )
    expected = hashlib.md5(
        b"299.000000:123456:password-2", usedforsecurity=False
    ).hexdigest()
    assert actual == expected


def test_result_signature_sorts_shp_parameters():
    payload = {"Shp_z": "2", "Shp_a": "1"}
    actual = robokassa_module.build_result_signature(
        "299.000000", "123456", "password-2", shp=payload
    )
    expected = hashlib.md5(
        b"299.000000:123456:password-2:Shp_a=1:Shp_z=2",
        usedforsecurity=False,
    ).hexdigest()
    assert actual == expected


def test_payment_url_contains_signed_required_fields(monkeypatch):
    service = _service(monkeypatch)
    url = service.create_payment_url(
        amount_rub=299, inv_id="123456", description="25 bananas"
    )
    query = parse_qs(urlparse(url).query)

    assert service.enabled is True
    assert query["MerchantLogin"] == ["demo-shop"]
    assert query["OutSum"] == ["299.00"]
    assert query["InvId"] == ["123456"]
    assert query["Description"] == ["25 bananas"]
    assert "IsTest" not in query
    expected = robokassa_module.build_checkout_signature(
        "demo-shop", "299.00", "123456", "live-password-1"
    )
    assert query["SignatureValue"] == [expected]


def test_result_verification_accepts_live_six_decimal_amount(monkeypatch):
    service = _service(monkeypatch)
    payload = {"OutSum": "299.000000", "InvId": "123456"}
    payload["SignatureValue"] = robokassa_module.build_result_signature(
        payload["OutSum"], payload["InvId"], "live-password-2"
    )

    assert service.verify_result(payload) == (True, "ok")
    assert robokassa_module.amounts_equal("299.000000", 299.0) is True


def test_result_verification_rejects_tampered_amount(monkeypatch):
    service = _service(monkeypatch)
    signature = robokassa_module.build_result_signature(
        "299.000000", "123456", "live-password-2"
    )
    assert service.verify_result(
        {
            "OutSum": "300.000000",
            "InvId": "123456",
            "SignatureValue": signature,
        }
    ) == (False, "invalid_signature")



def test_test_mode_requires_separate_test_passwords(monkeypatch):
    service = _service(monkeypatch, test_mode=True)
    assert service.enabled is False

def test_test_mode_uses_separate_test_passwords_when_configured(monkeypatch):
    monkeypatch.setenv("ROBOKASSA_TEST_PASSWORD1", "test-password-1")
    monkeypatch.setenv("ROBOKASSA_TEST_PASSWORD2", "test-password-2")
    service = _service(monkeypatch, test_mode=True)
    url = service.create_payment_url(amount_rub="10", inv_id="42", description="test")
    query = parse_qs(urlparse(url).query)

    assert query["IsTest"] == ["1"]
    expected = robokassa_module.build_checkout_signature(
        "demo-shop", "10.00", "42", "test-password-1"
    )
    assert query["SignatureValue"] == [expected]


def test_generated_invoice_id_is_valid_for_robokassa():
    invoice_id = robokassa_module.new_invoice_id()
    assert invoice_id.isdigit()
    assert 0 < int(invoice_id) <= robokassa_module.ROBOKASSA_MAX_INV_ID
