"""Telegram checkout order is consistent with Mini App payment priority."""

from inspect import unwrap

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


def test_direct_bot_checkout_hides_robokassa_even_when_provider_is_enabled():
    from bot.handlers.lava_checkout import _payment_options_keyboard

    markup = unwrap(_payment_options_keyboard)(
        "pro",
        stars=True,
        lava_card=True,
        lava_sbp=True,
        lava_foreign=False,
        lava_foreign_price_usd=None,
        crypto=True,
        freekassa=True,
        robokassa=True,
    )
    callbacks = [
        button.callback_data for row in markup.inline_keyboard for button in row
        if button.callback_data
    ]
    assert callbacks[:4] == [
        "buy_lava_card_pro", "buy_lava_sbp_pro",
        "freekassa_card_pro", "freekassa_sbp_pro",
    ]
    assert "buy_robokassa_pro" not in callbacks


def test_legacy_bot_checkout_keyboard_hides_robokassa_and_prefers_lava():
    from bot.handlers.robokassa_payments import _provider_keyboard

    markup = _provider_keyboard(
        "pro", robokassa=True, freekassa=True,
        stars=True, crypto=True, lava=True,
    )
    callbacks = [button.callback_data for button in _payment_buttons(markup)]
    assert callbacks[0] == "buy_lava_pro"
    assert "buy_robokassa_pro" not in callbacks
