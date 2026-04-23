"""Unit tests for bot/keyboards.py"""

import json
from unittest.mock import Mock, mock_open, patch

import pytest

from bot.keyboards import (get_admin_keyboard, get_balance_keyboard,
                           get_create_hub_keyboard, get_create_video_keyboard,
                           get_help_keyboard, get_main_menu_keyboard,
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
        "ux_create" in btn.callback_data
        for row in kb.inline_keyboard
        for btn in row
    )


def test_get_create_hub_keyboard():
    kb = get_create_hub_keyboard()
    assert kb.inline_keyboard
    assert any(
        "create_video_new" in btn.callback_data
        for row in kb.inline_keyboard
        for btn in row
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
    kb = get_payment_packages_keyboard(mock_prices["packages"])
    assert kb.inline_keyboard


def test_get_payment_provider_keyboard():
    kb = get_payment_provider_keyboard()
    assert kb.inline_keyboard
