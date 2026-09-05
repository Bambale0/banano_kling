from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.handlers import lava_checkout
from bot.handlers import prodamus_payments as prodamus
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


def test_text_bot_keeps_tribute_and_prodamus_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRODAMUS_PAYFORM_URL", "https://example.payform.ru/")
    monkeypatch.setenv("PRODAMUS_SECRET_KEY", "test-secret")
    monkeypatch.setenv("PRODAMUS_SYS", "test-system")

    tribute_markup = tribute.build_tribute_payment_method_keyboard(
        "mini",
        has_crypto=False,
        has_lava=True,
        has_stars=True,
    )
    combined_markup = prodamus._decorate_payment_keyboard(tribute_markup, "mini")

    buttons = [button for row in combined_markup.inline_keyboard for button in row]
    tribute_button = next(button for button in buttons if button.text == "СНГ И ЗАРУБЕЖНЫЕ")
    prodamus_button = next(
        button for button in buttons if button.text == prodamus.PRODAMUS_PAYMENT_BUTTON_TEXT
    )

    assert tribute_button.url == tribute.TRIBUTE_PACKAGE_LINKS["mini"]
    assert prodamus_button.callback_data == "prodamus_pay_mini"


def test_active_flat_payment_menu_includes_prodamus_before_reserve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRODAMUS_PAYFORM_URL", "https://example.payform.ru/")
    monkeypatch.setenv("PRODAMUS_SECRET_KEY", "test-secret")
    monkeypatch.setenv("PRODAMUS_SYS", "test-system")

    def fake_flat_keyboard(package_id: str, **_kwargs):
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💳 Картой", callback_data=f"card_{package_id}")],
                [InlineKeyboardButton(text="⚡ СБП", callback_data=f"sbp_{package_id}")],
                [InlineKeyboardButton(text="СНГ И ЗАРУБЕЖНЫЕ", url="https://example.test/reserve")],
                [InlineKeyboardButton(text="⭐ Stars", callback_data=f"stars_{package_id}")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_topup")],
            ]
        )

    monkeypatch.setattr(lava_checkout, "_payment_options_keyboard", fake_flat_keyboard)
    prodamus.install_prodamus_flat_text_payment_keyboard()

    markup = lava_checkout._payment_options_keyboard("start")
    buttons = [button for row in markup.inline_keyboard for button in row]
    texts = [button.text for button in buttons]
    assert prodamus.PRODAMUS_PAYMENT_BUTTON_TEXT in texts
    assert texts.index(prodamus.PRODAMUS_PAYMENT_BUTTON_TEXT) < texts.index("СНГ И ЗАРУБЕЖНЫЕ")
    button = next(
        item for item in buttons if item.text == prodamus.PRODAMUS_PAYMENT_BUTTON_TEXT
    )
    assert button.callback_data == "prodamus_pay_start"


def test_miniapp_keeps_tribute_and_prodamus_together() -> None:
    source = Path("frontend/miniapp-v0/components/balance-sheet.tsx").read_text(
        encoding="utf-8"
    )

    assert "const TRIBUTE_LINKS" in source
    assert "provider === ('tribute' as PaymentProvider)" in source
    assert "СНГ И ЗАРУБЕЖНЫЕ" in source
    assert "provider === 'prodamus'" in source
    assert "🇰🇿🇦🇲 Карта | СНГ" in source


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
        return {"ok": True, "already_completed": False}

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


@pytest.mark.asyncio
async def test_atomic_race_reports_duplicate_without_second_credit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_user(_telegram_id: int):
        return SimpleNamespace(id=99)

    async def fake_transaction(_order_id: str):
        return SimpleNamespace(
            provider="tribute",
            user_id=99,
            credits=50,
            status="pending",
        )

    async def fake_complete(_order_id: str, bot=None):
        return {"ok": True, "already_completed": True}

    monkeypatch.setattr(tribute, "get_or_create_user", fake_user)
    monkeypatch.setattr(tribute, "get_transaction_by_order", fake_transaction)
    monkeypatch.setattr(tribute, "_complete_transaction", fake_complete)

    result = await tribute._credit_tribute_purchase(
        SimpleNamespace(app={}),
        {
            "telegram_user_id": 12345,
            "purchase_id": 8003,
            "transaction_id": 9003,
        },
        tribute.TributeProduct(
            product_id=3,
            package_id="optimal",
            web_link=tribute.TRIBUTE_PACKAGE_LINKS["optimal"],
        ),
    )

    assert result["duplicate"] is True
    assert result["order_id"] == "tribute:8003"
