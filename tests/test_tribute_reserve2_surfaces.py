from __future__ import annotations

from pathlib import Path

from bot import keyboards
from bot.handlers import payments
from bot.handlers.tribute_payments import (
    TRIBUTE_PACKAGE_LINKS,
    build_tribute_payment_method_keyboard,
    install_tribute_text_payment_keyboard,
)


def _button_texts(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def test_text_bot_reserve2_opens_matching_tribute_package() -> None:
    markup = build_tribute_payment_method_keyboard(
        "optimal",
        has_crypto=True,
        has_lava=True,
        has_stars=True,
    )
    buttons = [button for row in markup.inline_keyboard for button in row]
    reserve = next(button for button in buttons if button.text == "Резерв 2")

    assert reserve.url == TRIBUTE_PACKAGE_LINKS["optimal"]
    assert reserve.url == "https://web.tribute.tg/p/Dxm"


def test_text_bot_stars_are_below_reserve2() -> None:
    markup = build_tribute_payment_method_keyboard(
        "mini",
        has_crypto=True,
        has_lava=True,
        has_stars=True,
    )
    labels = _button_texts(markup)

    assert "Резерв 2" in labels
    assert "⭐ Telegram Stars" in labels
    assert labels.index("Резерв 2") < labels.index("⭐ Telegram Stars")


def test_text_bot_payment_handler_is_patched_at_runtime() -> None:
    old_payments_keyboard = payments.get_payment_method_keyboard
    old_keyboards_keyboard = keyboards.get_payment_method_keyboard
    try:
        install_tribute_text_payment_keyboard()
        assert payments.get_payment_method_keyboard is build_tribute_payment_method_keyboard
        assert keyboards.get_payment_method_keyboard is build_tribute_payment_method_keyboard
    finally:
        payments.get_payment_method_keyboard = old_payments_keyboard
        keyboards.get_payment_method_keyboard = old_keyboards_keyboard


def test_miniapp_labels_tribute_button_as_reserve2() -> None:
    source = Path("frontend/miniapp-v0/components/balance-sheet.tsx").read_text(
        encoding="utf-8"
    )

    assert "Резерв 2" in source
    assert "Tribute · международная оплата" not in source
