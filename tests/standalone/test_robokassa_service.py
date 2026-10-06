from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from bot.services import robokassa_service as robokassa_module


def _service(monkeypatch, *, test_mode: bool = False):
    monkeypatch.setenv("ROBOKASSA_RECEIPT_TAX", "none")
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
        "demo-shop", "299.00", "123456", "live-password-1", receipt=query["Receipt"][0]
    )
    assert query["SignatureValue"] == [expected]


def test_payment_url_sanitizes_emoji_from_description(monkeypatch):
    service = _service(monkeypatch)
    url = service.create_payment_url(
        amount_rub=250,
        inv_id="1789057951890792199",
        description="Покупка 25 бананов (🍌 Старт)",
    )
    query = parse_qs(urlparse(url).query)

    assert query["Description"] == ["Покупка 25 бананов ( Старт)"]
    assert "🍌" not in query["Description"][0]


def test_description_falls_back_when_only_unsupported_symbols_are_given():
    assert robokassa_module.sanitize_description("🍌🔥") == "Оплата"


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
        "demo-shop", "10.00", "42", "test-password-1", receipt=query["Receipt"][0]
    )
    assert query["SignatureValue"] == [expected]


def test_generated_invoice_id_is_valid_for_robokassa():
    invoice_id = robokassa_module.new_invoice_id()
    assert invoice_id.isdigit()
    assert 0 < int(invoice_id) <= robokassa_module.ROBOKASSA_MAX_INV_ID


def test_checkout_sends_signed_nomenclature(monkeypatch):
    service = _service(monkeypatch)
    query = parse_qs(urlparse(service.create_payment_url(
        amount_rub="299.99", inv_id="123", description="Пополнение NEUROMIX"
    )).query)
    encoded = query["Receipt"][0]
    assert encoded.startswith("%7B")
    receipt = json.loads(unquote(encoded), parse_float=Decimal)
    assert receipt == {"items": [{
        "name": "Пополнение NEUROMIX", "quantity": 1,
        "sum": Decimal("299.99"), "tax": "none",
    }]}
    assert Decimal(query["OutSum"][0]) == receipt["items"][0]["sum"]
    expected = hashlib.md5(
        f"demo-shop:299.99:123:{encoded}:live-password-1".encode(),
        usedforsecurity=False,
    ).hexdigest()
    assert query["SignatureValue"] == [expected]


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "sNaN", "Infinity", "-Infinity", "abc", None])
def test_checkout_rejects_invalid_amounts(monkeypatch, amount):
    service = _service(monkeypatch)
    with pytest.raises(ValueError):
        service.create_payment_url(amount_rub=amount, inv_id="1", description="Баланс")


@pytest.mark.parametrize("amount, expected", [("0.01", "0.01"), ("1.005", "1.01"), ("299.999", "300.00"), ("123456789.12", "123456789.12")])
def test_receipt_total_exactly_matches_outsum(monkeypatch, amount, expected):
    service = _service(monkeypatch)
    query = parse_qs(urlparse(service.create_payment_url(amount_rub=amount, inv_id="1", description="Баланс")).query)
    receipt = json.loads(unquote(query["Receipt"][0]), parse_float=Decimal)
    assert query["OutSum"] == [expected]
    assert receipt["items"][0]["sum"] == Decimal(expected)


def test_missing_tax_blocks_new_checkout_but_not_old_callback(monkeypatch):
    service = _service(monkeypatch)
    service.receipt_tax = ""
    with pytest.raises(ValueError, match="ROBOKASSA_RECEIPT_TAX"):
        service.create_payment_url(amount_rub=1, inv_id="1", description="Баланс")
    payload = {"OutSum": "1.000000", "InvId": "1"}
    payload["SignatureValue"] = robokassa_module.build_result_signature("1.000000", "1", "live-password-2")
    assert service.verify_result(payload) == (True, "ok")


@pytest.mark.parametrize("field,value", [
    ("receipt_tax", "npd"), ("receipt_tax", "vat4"),
    ("receipt_payment_method", "paid"), ("receipt_payment_object", "banana"),
])
def test_invalid_receipt_config_is_rejected(monkeypatch, field, value):
    service = _service(monkeypatch)
    setattr(service, field, value)
    with pytest.raises(ValueError):
        service.create_payment_url(amount_rub=1, inv_id="1", description="Баланс")


def test_receipt_name_is_separate_sanitized_and_bounded(monkeypatch):
    service = _service(monkeypatch)
    query = parse_qs(urlparse(service.create_payment_url(
        amount_rub=1, inv_id="1", description="UI title",
        receipt_name="Услуга 🍌 & + % \" " + "я"*150,
    )).query)
    name = json.loads(unquote(query["Receipt"][0]))["items"][0]["name"]
    assert query["Description"] == ["UI title"]
    assert len(name) == 128
    assert name.startswith("Услуга")
    assert all(c not in name for c in ["🍌", "&", "+", "%", '"'])


def test_receipt_is_inside_signature_before_password_and_sorted_shp():
    encoded = "%7B%22items%22%3A%5B%5D%7D"
    expected = hashlib.sha256(
        f"shop:8.96:123:{encoded}:pw:Shp_a=1:Shp_z=2".encode()
    ).hexdigest()
    assert robokassa_module.build_checkout_signature(
        "shop", "8.96", "123", "pw", receipt=encoded,
        algorithm="sha256", shp={"Shp_z": 2, "Shp_a": 1},
    ) == expected


def test_receipt_tampering_changes_signature():
    sign = robokassa_module.build_checkout_signature
    assert sign("shop", "1", "1", "pw", receipt="%7B%7D") != sign("shop", "1", "1", "pw", receipt="%7B%20%7D")


def test_explicit_receipt_classification_is_preserved(monkeypatch):
    service = _service(monkeypatch)
    service.receipt_payment_method = "advance"
    service.receipt_payment_object = "payment"
    receipt = json.loads(unquote(service.build_receipt("25.01", "Баланс")))
    assert receipt["items"][0]["payment_method"] == "advance"
    assert receipt["items"][0]["payment_object"] == "payment"
    assert "sno" not in receipt
