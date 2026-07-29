from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.handlers.trend_video_compat import (
    TREND_VIDEO_MODELS,
    TREND_VIDEO_TAG,
    _add_video_upload_button,
    is_video_trend,
)


def test_video_trend_detection_supports_tag_category_and_model() -> None:
    assert is_video_trend({"tags": [TREND_VIDEO_TAG]}) is True
    assert is_video_trend({"category": "video", "tags": []}) is True
    assert is_video_trend({"model": "v3_pro", "tags": []}) is True
    assert is_video_trend({"model": "banana_pro", "tags": ["trend"]}) is False
    assert is_video_trend(None) is False


def test_video_model_ids_are_unique() -> None:
    model_ids = [model_id for model_id, _label in TREND_VIDEO_MODELS]
    assert model_ids
    assert len(model_ids) == len(set(model_ids))


def test_video_upload_button_is_added_once() -> None:
    original = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Повторить", callback_data="noop")],
            [InlineKeyboardButton(text="Загрузить фото", callback_data="trend_add")],
        ]
    )

    updated = _add_video_upload_button(original)
    repeated = _add_video_upload_button(updated)

    callbacks = [
        button.callback_data
        for row in repeated.inline_keyboard
        for button in row
    ]
    assert callbacks.count("trend_video_add") == 1
    assert original.inline_keyboard != repeated.inline_keyboard
