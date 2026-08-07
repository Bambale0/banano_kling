from __future__ import annotations

from aiogram import types

from bot.handlers.seedance_25_new_priority import (
    MODEL_KEY,
    MODEL_LABEL,
    _move_seedance_first,
    _prioritize_video_keyboard,
)


def test_seedance_model_is_first_and_bright_new_label():
    models = [
        {"id": "kling", "label": "Kling"},
        {"id": MODEL_KEY, "label": "Seedance 2.5"},
        {"id": "veo", "label": "Veo"},
    ]

    ordered = _move_seedance_first(models)

    assert [item["id"] for item in ordered] == [MODEL_KEY, "kling", "veo"]
    assert ordered[0]["label"] == MODEL_LABEL
    assert ordered[0]["is_new"] is True
    assert ordered[0]["priority"] == 1000


def test_seedance_telegram_button_is_first_row(monkeypatch):
    import bot.handlers.seedance_25_new_priority as module

    monkeypatch.setattr(
        module.preset_manager,
        "get_video_cost_per_second",
        lambda *args, **kwargs: 4,
    )

    def original(current_model="v3_pro", user_id=None):
        return types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="Kling", callback_data="v_model_v3_pro")],
                [types.InlineKeyboardButton(text="Seedance", callback_data="v_model_seedance_2_5")],
                [types.InlineKeyboardButton(text="Главное меню", callback_data="back_main")],
            ]
        )

    markup = _prioritize_video_keyboard(original)("v3_pro", user_id=123)

    assert markup.inline_keyboard[0][0].callback_data == "v_model_seedance_2_5"
    assert "🔥🆕 NEW" in markup.inline_keyboard[0][0].text
    assert markup.inline_keyboard[1][0].callback_data == "v_model_v3_pro"
