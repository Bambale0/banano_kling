"""Telegram checkout order is consistent with Mini App payment priority."""

from bot.keyboards import get_payment_method_keyboard


def _payment_buttons(markup):
    return [
        button
        for row in markup.inline_keyboard
        for button in row
        if (button.callback_data or "").startswith("buy_")
    ]


def test_lava_is_first_visible_telegram_payment_method():
    markup = get_payment_method_keyboard(
        "pro", has_crypto=True, has_lava=True, has_stars=True
    )
    buttons = _payment_buttons(markup)
    assert [button.callback_data for button in buttons] == [
        "buy_lava_pro", "buy_stars_pro", "buy_crypto_pro",
    ]
    assert buttons[0].text.startswith("💳 Lava.top")
    assert all("robokassa" not in (button.text or "").lower() for button in buttons)


def test_unconfigured_lava_is_not_advertised():
    markup = get_payment_method_keyboard(
        "pro", has_crypto=True, has_lava=False, has_stars=True
    )
    assert [button.callback_data for button in _payment_buttons(markup)] == [
        "buy_stars_pro", "buy_crypto_pro",
    ]
