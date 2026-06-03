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
            "photo_limit_text": "до 2 000 фото",
            "popular": True,
        }
    ]
    kb = get_payment_packages_keyboard(packages)
    assert kb.inline_keyboard
    button_text = " ".join(
        btn.text for row in kb.inline_keyboard for btn in row if btn.callback_data
    )
    assert "Mini" in button_text
    assert "месяц" in button_text
    assert "до 2 000 фото" in button_text


def test_get_payment_provider_keyboard():
    kb = get_payment_provider_keyboard()
    assert kb.inline_keyboard
