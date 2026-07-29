from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

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
