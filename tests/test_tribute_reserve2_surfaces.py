from __future__ import annotations

from pathlib import Path

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.handlers import lava_checkout
from bot.handlers.miniapp_lava_payment_methods_compat import (
    _decorate_text_payment_options,
)
from bot.tribute_config import TRIBUTE_PACKAGE_LINKS


def _button_texts(markup: InlineKeyboardMarkup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def _button(markup: InlineKeyboardMarkup, text: str) -> InlineKeyboardButton:
    return next(
        button
        for row in markup.inline_keyboard
        for button in row
        if button.text == text
    )


def test_live_text_bot_keyboard_has_reserve2_after_sbp() -> None:
    markup = lava_checkout._payment_options_keyboard(
        "optimal",
        stars=True,
        lava_card=True,
        lava_sbp=True,
        lava_foreign=True,
        lava_foreign_price_usd=10.0,
        crypto=True,
        freekassa=True,
    )
    labels = _button_texts(markup)

    assert labels[:3] == ["💳 Картой", "⚡ СБП", "СНГ И ЗАРУБЕЖНЫЕ"]
    assert _button(markup, "СНГ И ЗАРУБЕЖНЫЕ").url == TRIBUTE_PACKAGE_LINKS["optimal"]
    assert _button(markup, "СНГ И ЗАРУБЕЖНЫЕ").url == "https://web.tribute.tg/p/Dxm"
    assert labels.index("СНГ И ЗАРУБЕЖНЫЕ") < labels.index("⭐ Stars")
    assert labels.index("₿ Криптовалюта") < labels.index("⭐ Stars")
    assert labels[-1] == "◀️ Назад"


def test_reserve2_decorator_matches_production_flat_menu_order() -> None:
    base = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Картой", callback_data="card")],
            [InlineKeyboardButton(text="⚡ СБП", callback_data="sbp")],
            [InlineKeyboardButton(text="🇷🇺 РФ — KASSA (резерв)", callback_data="kassa")],
            [InlineKeyboardButton(text="🌍 Зарубежная карта", callback_data="foreign")],
            [InlineKeyboardButton(text="🌍 PayPal", callback_data="paypal")],
            [InlineKeyboardButton(text="⭐ Stars", callback_data="stars")],
            [InlineKeyboardButton(text="₿ Криптовалюта", callback_data="crypto")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_topup")],
        ]
    )

    markup = _decorate_text_payment_options(base, "optimal")

    assert _button_texts(markup) == [
        "💳 Картой",
        "⚡ СБП",
        "СНГ И ЗАРУБЕЖНЫЕ",
        "🇷🇺 РФ — KASSA (резерв)",
        "🌍 Зарубежная карта",
        "🌍 PayPal",
        "₿ Криптовалюта",
        "⭐ Stars",
        "◀️ Назад",
    ]
    assert _button(markup, "СНГ И ЗАРУБЕЖНЫЕ").url == "https://web.tribute.tg/p/Dxm"


def test_all_six_reserve2_links_are_configured() -> None:
    assert TRIBUTE_PACKAGE_LINKS == {
        "mini": "https://web.tribute.tg/p/Dxi",
        "start": "https://web.tribute.tg/p/Dxn",
        "optimal": "https://web.tribute.tg/p/Dxm",
        "pro": "https://web.tribute.tg/p/Dxo",
        "studio": "https://web.tribute.tg/p/Dxp",
        "business": "https://web.tribute.tg/p/Dxq",
    }


def test_miniapp_labels_tribute_button_as_reserve2() -> None:
    source = Path("frontend/miniapp-v0/components/balance-sheet.tsx").read_text(
        encoding="utf-8"
    )

    assert "СНГ И ЗАРУБЕЖНЫЕ" in source
    assert "Tribute · международная оплата" not in source
