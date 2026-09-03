from __future__ import annotations

import hashlib
import hmac
from types import SimpleNamespace

import pytest

from bot.handlers import tribute_payments as tribute


def test_tribute_package_links_are_exact() -> None:
    assert tribute.TRIBUTE_PACKAGE_LINKS == {
        "mini": "https://web.tribute.tg/p/Dxi",
        "start": "https://web.tribute.tg/p/Dxn",
        "optimal": "https://web.tribute.tg/p/Dxm",
        "pro": "https://web.tribute.tg/p/Dxo",
        "studio": "https://web.tribute.tg/p/Dxp",
        "business": "https://web.tribute.tg/p/Dxq",
    }


def test_tribute_signature_uses_raw_body_hmac_sha256() -> None:
    raw_body = b'{"name":"new_digital_product","payload":{"purchase_id":7}}'
    api_key = "tribute-test-key"
    signature = hmac.new(api_key.encode(), raw_body, hashlib.sha256).hexdigest()

    assert tribute.verify_tribute_signature(raw_body, signature, api_key)
    assert tribute.verify_tribute_signature(raw_body, f"sha256={signature}", api_key)
    assert not tribute.verify_tribute_signature(raw_body + b" ", signature, api_key)
    assert not tribute.verify_tribute_signature(raw_body, "deadbeef", api_key)
    assert not tribute.verify_tribute_signature(raw_body, signature, "")


def test_product_api_row_is_mapped_only_by_known_tribute_link() -> None:
    configured = tribute._configured_tribute_links()
    product = tribute._product_from_api_row(
        {
            "id": 456,
            "webLink": "https://web.tribute.tg/p/Dxm",
            "amount": 500,
            "currency": "rub",
        },
        configured,
    )
    assert product is not None
    assert product.product_id == 456
    assert product.package_id == "optimal"
    assert product.amount == 500
    assert product.currency == "RUB"

    assert tribute._product_from_api_row(
        {"id": 999, "webLink": "https://web.tribute.tg/p/unknown"}, configured
    ) is None


def test_payload_amount_and_currency_must_match_resolved_product() -> None:
    product = tribute.TributeProduct(
        product_id=456,
        package_id="optimal",
        web_link="https://web.tribute.tg/p/Dxm",
        amount=500,
        currency="RUB",
    )
    tribute._validate_payload_against_product(
        {"amount": 500, "currency": "rub"}, product
    )

    with pytest.raises(tribute.TributeProductError, match="amount mismatch"):
        tribute._validate_payload_against_product(
            {"amount": 501, "currency": "RUB"}, product
        )
    with pytest.raises(tribute.TributeProductError, match="currency mismatch"):
        tribute._validate_payload_against_product(
            {"amount": 500, "currency": "USD"}, product
        )


@pytest.mark.asyncio
async def test_completed_tribute_purchase_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_user(_telegram_id: int):
        return SimpleNamespace(id=77)

    async def fake_transaction(_order_id: str):
        return SimpleNamespace(
            provider="tribute",
            user_id=77,
            credits=15,
            status="completed",
        )

    async def should_not_create(**_kwargs):
        raise AssertionError("duplicate purchase must not create another transaction")

    async def should_not_complete(*_args, **_kwargs):
        raise AssertionError("duplicate purchase must not credit twice")

    monkeypatch.setattr(tribute, "get_or_create_user", fake_user)
    monkeypatch.setattr(tribute, "get_transaction_by_order", fake_transaction)
    monkeypatch.setattr(tribute, "create_transaction", should_not_create)
    monkeypatch.setattr(tribute, "_complete_transaction", should_not_complete)

    result = await tribute._credit_tribute_purchase(
        SimpleNamespace(app={}),
        {
            "telegram_user_id": 12345,
            "purchase_id": 8001,
            "transaction_id": 9001,
        },
        tribute.TributeProduct(
            product_id=1,
            package_id="mini",
            web_link=tribute.TRIBUTE_PACKAGE_LINKS["mini"],
        ),
    )

    assert result["status"] == "ok"
    assert result["duplicate"] is True
    assert result["order_id"] == "tribute:8001"


@pytest.mark.asyncio
async def test_new_tribute_purchase_uses_existing_atomic_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, object] = {}

    async def fake_user(_telegram_id: int):
        return SimpleNamespace(id=88)

    async def fake_transaction(_order_id: str):
        return None

    async def fake_create(**kwargs):
        recorded.update(kwargs)
        return True

    async def fake_complete(order_id: str, bot=None):
        recorded["completed_order_id"] = order_id
        recorded["bot"] = bot
        return {"action": "completed"}

    monkeypatch.setattr(tribute, "get_or_create_user", fake_user)
    monkeypatch.setattr(tribute, "get_transaction_by_order", fake_transaction)
    monkeypatch.setattr(tribute, "create_transaction", fake_create)
    monkeypatch.setattr(tribute, "_complete_transaction", fake_complete)

    fake_bot = object()
    result = await tribute._credit_tribute_purchase(
        SimpleNamespace(app={"bot": fake_bot}),
        {
            "telegram_user_id": 12345,
            "purchase_id": 8002,
            "transaction_id": 9002,
        },
        tribute.TributeProduct(
            product_id=2,
            package_id="start",
            web_link=tribute.TRIBUTE_PACKAGE_LINKS["start"],
        ),
    )

    assert recorded["order_id"] == "tribute:8002"
    assert recorded["payment_id"] == "tribute:9002"
    assert recorded["provider"] == "tribute"
    assert recorded["credits"] == 25
    assert recorded["status"] == "pending"
    assert recorded["completed_order_id"] == "tribute:8002"
    assert recorded["bot"] is fake_bot
    assert result["credits"] == 25
    assert result["duplicate"] is False
