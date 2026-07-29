from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.handlers.trend_text_upload import (
    TREND_IMAGE_MODELS,
    _add_admin_upload_button,
    _trend_model_keyboard,
)
from bot.handlers.trends_compat import (
    TREND_TAG,
    _replace_prompt_buttons,
    is_trend_prompt,
)


def test_only_system_tag_marks_prompt_as_trend() -> None:
    assert is_trend_prompt({"tags": [TREND_TAG]}) is True
    assert is_trend_prompt({"tags": ["Trend", "photo"]}) is True
    assert is_trend_prompt({"tags": ["portrait"]}) is False
    assert is_trend_prompt(None) is False


def test_prompt_buttons_are_replaced_with_trends() -> None:
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📚 Библиотека промптов",
                    callback_data="menu_prompts",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📚 Промпты",
                    callback_data="admin_prompts",
                ),
                InlineKeyboardButton(text="Лента", callback_data="menu_feed"),
            ],
        ]
    )

    updated = _replace_prompt_buttons(markup)

    assert updated.inline_keyboard[0][0].text == "🔥 Тренды"
    assert updated.inline_keyboard[0][0].callback_data == "menu_trends"
    assert updated.inline_keyboard[1][0].text == "🔥 Тренды"
    assert updated.inline_keyboard[1][0].callback_data == "menu_trends"
    assert updated.inline_keyboard[1][1].callback_data == "menu_feed"


def test_original_markup_is_not_mutated() -> None:
    original = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Промпты", callback_data="menu_prompts")]
        ]
    )

    updated = _replace_prompt_buttons(original)

    assert original.inline_keyboard[0][0].callback_data == "menu_prompts"
    assert updated.inline_keyboard[0][0].callback_data == "menu_trends"


def test_admin_upload_button_is_added_once_near_top() -> None:
    original = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Навигация", callback_data="noop")],
            [InlineKeyboardButton(text="Повторить", callback_data="repeat")],
            [InlineKeyboardButton(text="Главное меню", callback_data="back_main")],
        ]
    )

    updated = _add_admin_upload_button(original)
    repeated = _add_admin_upload_button(updated)

    assert updated.inline_keyboard[1][0].text == "➕ Загрузить тренд"
    assert updated.inline_keyboard[1][0].callback_data == "trend_add"
    assert sum(
        button.callback_data == "trend_add"
        for row in repeated.inline_keyboard
        for button in row
    ) == 1
    assert all(
        button.callback_data != "trend_add"
        for row in original.inline_keyboard
        for button in row
    )


def test_text_upload_model_keyboard_uses_canonical_image_models() -> None:
    keyboard = _trend_model_keyboard()
    callbacks = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if str(button.callback_data or "").startswith("trend_model:")
    ]

    assert callbacks == [f"trend_model:{model_id}" for model_id, _ in TREND_IMAGE_MODELS]
    assert "trend_model:nanobanana" not in callbacks
    assert keyboard.inline_keyboard[-1][0].callback_data == "trend_add_cancel"
