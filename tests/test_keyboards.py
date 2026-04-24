"""Unit tests for bot/keyboards.py"""

import json
from unittest.mock import Mock, mock_open, patch

import pytest

from bot.keyboards import (get_admin_keyboard, get_balance_keyboard,
                           get_create_hub_keyboard, get_create_video_keyboard,
                           get_help_keyboard, get_image_result_keyboard,
                           get_main_menu_keyboard,
                           get_payment_packages_keyboard,
                           get_payment_provider_keyboard, get_support_keyboard,
                           get_topup_keyboard, get_video_media_step_keyboard,
                           get_video_model_label, load_prices)


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
        btn.callback_data and "create_image_text_new" in btn.callback_data
        for row in kb.inline_keyboard
        for btn in row
    )


def test_get_main_menu_keyboard_contains_mini_app_button():
    kb = get_main_menu_keyboard(10)
    assert any(
        getattr(btn, "web_app", None) is not None and btn.text == "🚀 Открыть Mini App"
        for row in kb.inline_keyboard
        for btn in row
    )


def test_get_create_hub_keyboard():
    kb = get_create_hub_keyboard()
    assert kb.inline_keyboard
    assert any(
        "quick_reels_video" in btn.callback_data
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
        "video_change_media" in btn.callback_data
        for row in kb.inline_keyboard
        for btn in row
    )


def test_get_create_video_keyboard_for_kling_25_shows_doc_settings():
    kb = get_create_video_keyboard(current_model="v26_pro")
    callback_ids = [
        btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data
    ]
    assert "kling_negative_prompt_edit" in callback_ids
    assert "kling_cfg_scale_edit" in callback_ids


def test_get_video_media_step_keyboard_for_avatar():
    kb = get_video_media_step_keyboard(
        current_v_type="avatar",
        current_model="avatar_std",
        has_start_image=True,
        has_avatar_audio=False,
    )
    button_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    callback_ids = [
        btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data
    ]
    assert any("Аватар: загружено" in text for text in button_texts)
    assert any("Аудио: не загружено" in text for text in button_texts)
    assert "video_media_continue" in callback_ids


def test_get_video_model_label_for_new_models():
    assert get_video_model_label("v26_pro") == "Kling 2.5 Turbo Pro"
    assert get_video_model_label("avatar_std") == "Kling AI Avatar Standard"
    assert get_video_model_label("avatar_pro") == "Kling AI Avatar Pro"


def test_get_image_result_keyboard_contains_repeat_and_main_menu():
    kb = get_image_result_keyboard("https://example.com/image.png", task_id="img_123")
    button_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    callback_ids = [
        btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data
    ]
    assert "🔁 Повторить" in button_texts
    assert "repeat_image_img_123" in callback_ids
    assert "back_main" in callback_ids


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
