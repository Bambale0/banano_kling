from bot.handlers.admin_user_ban import _user_card_keyboard, _user_card_text


def _callback_values(markup) -> list[str]:
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]


def test_active_user_card_offers_ban_and_keeps_existing_actions():
    telegram_id = 123456789
    markup = _user_card_keyboard(telegram_id, is_banned=False)
    callbacks = _callback_values(markup)

    assert f"admin_ban_user_{telegram_id}" in callbacks
    assert f"admin_unban_user_{telegram_id}" not in callbacks
    assert f"admin_add_credits_{telegram_id}" in callbacks
    assert f"admin_deduct_credits_{telegram_id}" in callbacks
    assert f"admin_partner_view_{telegram_id}" in callbacks


def test_banned_user_card_offers_unban_and_shows_status():
    telegram_id = 987654321
    stats = {
        "is_banned": True,
        "credits": 7.5,
        "generations": 12,
        "total_spent": 24,
        "member_since": "2026-08-01",
        "referrals_count": 2,
        "referral_earned": 3,
        "referral_code": "ABC123",
    }

    text = _user_card_text(telegram_id, stats)
    callbacks = _callback_values(_user_card_keyboard(telegram_id, is_banned=True))

    assert "🔴 Заблокирован" in text
    assert f"admin_unban_user_{telegram_id}" in callbacks
    assert f"admin_ban_user_{telegram_id}" not in callbacks
