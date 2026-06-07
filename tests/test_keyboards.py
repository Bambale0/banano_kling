"""Unit tests for bot/keyboards.py"""

import json
from unittest.mock import Mock, mock_open, patch

import pytest

from bot.keyboards import (get_admin_keyboard, get_balance_keyboard,
                           get_create_video_keyboard, get_help_keyboard,
                           get_image_result_keyboard,
                           get_main_menu_keyboard,
                           get_payment_packages_keyboard,
                           get_payment_provider_keyboard, get_support_keyboard,
                           get_topup_keyboard, load_prices)


@pytest.fixture
def mock_prices():
    return {
        "packages": [
            {"id": "mini", "name": "Mini", "credits": 15, "price_rub": 150},
            {"id": "standard", "name": "Standard", "credits": 30, "price_rub": 250},
        ],
        "costs_reference": {
            "image_models": {"flux_pro": 3},
            "video_models": {"v3_std": {"base": 6, "duration_costs": {"5": 6}}},
        },
    }


def test_load_prices(mock_prices):
    with patch("builtins.open", mock_open(read_data=json.dumps(mock_prices))):
        with patch("bot.keyboards.os.path.join", return_value="dummy"):
            prices = load_prices()
            assert prices["packages"] == mock_prices["packages"]


def test_get_main_menu_keyboard():
    kb = get_main_menu_keyboard(10)
    assert kb.inline_keyboard
    rows = [[btn.callback_data for btn in row] for row in kb.inline_keyboard]
    callback_data = [
        btn.callback_data
        for row in kb.inline_keyboard
        for btn in row
        if btn.callback_data
    ]
    assert any(
        "create_video_new" in btn.callback_data
        for row in kb.inline_keyboard
        for btn in row
    )
    assert any(
        "menu_feed" in btn.callback_data
        for row in kb.inline_keyboard
        for btn in row
    )
    assert "recurring_status" not in callback_data
    assert ["menu_partner", "menu_support"] in rows


def test_main_menu_mini_app_button_is_admin_only(monkeypatch):
    monkeypatch.setattr("bot.keyboards.config.ADMIN_IDS_STR", "123")
    monkeypatch.setattr("bot.keyboards.config.MINI_APP_URL", "https://example.com/mini")

    user_kb = get_main_menu_keyboard(10, user_id=456)
    admin_kb = get_main_menu_keyboard(10, user_id=123)

    assert not any(
        getattr(btn, "web_app", None)
        for row in user_kb.inline_keyboard
        for btn in row
    )
    mini_buttons = [
        btn
        for row in admin_kb.inline_keyboard
        for btn in row
        if getattr(btn, "web_app", None)
    ]
    assert len(mini_buttons) == 1
    assert mini_buttons[0].text == "🧩 Mini App"
    assert mini_buttons[0].web_app.url == "https://example.com/mini"


def test_main_menu_hides_mini_app_without_url(monkeypatch):
    monkeypatch.setattr("bot.keyboards.config.ADMIN_IDS_STR", "123")
    monkeypatch.setattr("bot.keyboards.config.MINI_APP_URL", "")

    kb = get_main_menu_keyboard(10, user_id=123)

    assert not any(
        getattr(btn, "web_app", None)
        for row in kb.inline_keyboard
        for btn in row
    )


def test_get_image_result_keyboard_has_feed_publish():
    kb = get_image_result_keyboard("task1", "http://image.url")
    assert any(
        "feed_publish_task1" in btn.callback_data
        for row in kb.inline_keyboard
        for btn in row
        if btn.callback_data
    )


def test_get_admin_keyboard():
    kb = get_admin_keyboard()
    assert kb.inline_keyboard
    assert any(
        "admin_reload" in btn.callback_data for row in kb.inline_keyboard for btn in row
    )


def test_get_create_video_keyboard():
    kb = get_create_video_keyboard()
    assert kb.inline_keyboard
    assert any(
        "v_type_text" in btn.callback_data for row in kb.inline_keyboard for btn in row
    )


def test_get_topup_keyboard(mock_prices):
    with patch("bot.keyboards.PACKAGES", mock_prices["packages"]):
        kb = get_topup_keyboard()
        assert kb.inline_keyboard


def test_get_balance_keyboard():
    kb = get_balance_keyboard(10)
    assert kb.inline_keyboard
    assert "menu_topup" in str(kb.inline_keyboard)


def test_get_support_keyboard():
    kb = get_support_keyboard()
    assert kb.inline_keyboard


def test_get_help_keyboard():
    kb = get_help_keyboard()
    assert kb.inline_keyboard


def test_get_payment_packages_keyboard(mock_prices):
    packages = [
        {
            **mock_prices["packages"][0],
            "period": "месяц",
            "photo_limit_text": "до 100 фото",
            "subscription_days": 30,
            "popular": True,
        }
    ]
    kb = get_payment_packages_keyboard(packages)
    assert kb.inline_keyboard
    button_text = " ".join(
        btn.text for row in kb.inline_keyboard for btn in row if btn.callback_data
    )
    assert "Mini · 150₽" in button_text
    assert "месяц" in button_text
    assert "до 100 фото" in button_text


def test_get_payment_packages_keyboard_splits_credits_and_subscriptions():
    packages = [
        {
            "id": "coin50",
            "name": "50 BoomCoin",
            "credits": 50,
            "price_rub": 499,
            "bonus_credits": 0,
        },
        {
            "id": "pro",
            "name": "Pro",
            "credits": 199,
            "price_rub": 2990,
            "period": "месяц",
            "photo_limit_text": "до 180 фото",
            "video_limit_text": "4 видео",
            "subscription_days": 30,
            "includes_pro": True,
        },
    ]

    kb = get_payment_packages_keyboard(packages, provider="tbank")
    rows = [[btn.text for btn in row] for row in kb.inline_keyboard]
    button_text = " ".join(text for row in rows for text in row)

    assert ["✅ 💳 Т-Банк", "₿ Crypto Bot"] in rows
    assert ["🔁 Автопродление"] in rows
    assert ["🪙 BoomCoin без подписки"] in rows
    assert "50 BoomCoin · 499₽" in button_text
    assert ["🧾 Подписки"] in rows
    assert "Pro · 2990₽ · месяц · до 180 фото" in button_text
    assert "Banana Pro" not in button_text


def test_get_payment_packages_keyboard_uses_kind_for_subscriptions():
    packages = [
        {
            "id": "coin50",
            "kind": "credits",
            "name": "50 BoomCoin",
            "credits": 50,
            "price_rub": 499,
        },
        {
            "id": "boom",
            "kind": "subscription",
            "name": "Boom",
            "credits": 50,
            "price_rub": 1490,
            "period": "месяц",
            "photo_limit_text": "до 100 фото",
        },
    ]

    kb = get_payment_packages_keyboard(packages, provider="tbank")
    rows = [[btn.text for btn in row] for row in kb.inline_keyboard]
    button_text = " ".join(text for row in rows for text in row)

    assert ["🧾 Подписки"] in rows
    assert "Boom · 1490₽ · месяц · до 100 фото" in button_text
    assert "buy_tbank_boom" in str(kb.inline_keyboard)


def test_get_payment_provider_keyboard():
    kb = get_payment_provider_keyboard()
    assert kb.inline_keyboard
