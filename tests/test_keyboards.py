"""Unit tests for bot/keyboards.py"""

import json
import logging
import importlib
from unittest.mock import AsyncMock, Mock, mock_open, patch

import pytest

from bot.keyboards import (get_admin_keyboard, get_balance_keyboard,
                           get_create_hub_keyboard, get_create_video_keyboard,
                           get_help_keyboard, get_image_result_keyboard,
                           get_main_menu_keyboard,
                           get_payment_packages_keyboard,
                           get_payment_provider_keyboard, get_support_keyboard,
                           get_topup_keyboard, get_video_media_step_keyboard,
                           get_video_model_label,
                           get_video_model_selection_keyboard, load_prices)
from bot.handlers.image_analyzer import _format_photo_prompt_result_text
from bot.services.gemini_omni_service import GeminiOmniService
from bot.services.photo_prompt_service import (
    PhotoPromptService,
    _is_fast_fallback_application_error,
)


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
    assert any(
        "admin_finance" in btn.callback_data for row in kb.inline_keyboard for btn in row
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


def test_get_create_video_keyboard_for_gemini_omni_video_shows_doc_settings():
    kb = get_create_video_keyboard(current_model="gemini_omni_video")
    callback_ids = [
        btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data
    ]
    assert "omni_resolution_720p" in callback_ids
    assert "omni_resolution_1080p" in callback_ids
    assert "omni_resolution_4k" in callback_ids
    assert "omni_seed_edit" in callback_ids
    assert "omni_audio_ids_edit" in callback_ids
    assert "omni_character_ids_edit" in callback_ids


def test_video_model_selection_groups_gemini_omni_modes():
    kb = get_video_model_selection_keyboard(current_model="gemini_omni_video")
    button_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    callback_ids = [
        btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data
    ]
    assert "v_model_gemini_omni" in callback_ids
    assert "v_model_gemini_omni_video" not in callback_ids
    assert "v_model_gemini_omni_audio" not in callback_ids
    assert "v_model_gemini_omni_character" not in callback_ids
    assert any("✅ 🔷 Gemini Omni" in text for text in button_texts)


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


def test_get_video_media_step_keyboard_uses_model_video_ref_limit():
    kb = get_video_media_step_keyboard(
        current_v_type="video",
        current_model="seedance_2",
        reference_video_count=2,
        max_reference_video_count=3,
    )
    button_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "📹 Видео-референсы: 2/3" in button_texts


def test_get_video_model_label_for_new_models():
    assert get_video_model_label("v26_pro") == "Kling 2.5 Turbo Pro"
    assert get_video_model_label("avatar_std") == "Kling AI Avatar Standard"
    assert get_video_model_label("avatar_pro") == "Kling AI Avatar Pro"
    assert get_video_model_label("gemini_omni") == "Gemini Omni"
    assert get_video_model_label("gemini_omni_video") == "Gemini Omni Video"
    assert get_video_model_label("gemini_omni_audio") == "Gemini Omni Audio"
    assert get_video_model_label("gemini_omni_character") == "Gemini Omni Character"


@pytest.mark.asyncio
async def test_gemini_omni_video_payload_uses_jobs_api():
    service = GeminiOmniService(kie_key="test")
    service._kie_post = AsyncMock(
        return_value={"task_id": "task_gemini", "status": "pending"}
    )

    result = await service.generate_video(
        prompt="make a city scene",
        duration=8,
        aspect_ratio="9:16",
        resolution="1080p",
        image_urls=["https://example.com/a.png"],
        audio_ids=["audio_1", "audio_2"],
        video_list=[{"video_url": "https://example.com/ref.mp4", "duration": 10}],
        character_ids=["character_1"],
        seed=42,
        callBackUrl="https://example.com/cb",
    )

    assert result["task_id"] == "task_gemini"
    endpoint, payload = service._kie_post.await_args.args
    assert endpoint == service.CREATE_TASK_ENDPOINT
    assert payload["model"] == "gemini-omni-video"
    assert payload["callBackUrl"] == "https://example.com/cb"
    assert payload["input"]["duration"] == "8"
    assert payload["input"]["aspect_ratio"] == "9:16"
    assert payload["input"]["resolution"] == "1080p"
    assert payload["input"]["audio_ids"] == ["audio_1"]
    assert payload["input"]["video_list"] == [
        {"url": "https://example.com/ref.mp4", "start": 0, "ends": 10}
    ]
    assert payload["input"]["character_ids"] == ["character_1"]
    assert payload["input"]["seed"] == 42


@pytest.mark.asyncio
async def test_gemini_omni_audio_and_character_return_immediate_assets():
    service = GeminiOmniService(kie_key="test")
    service._kie_post_raw = AsyncMock(
        side_effect=[
            {
                "code": 0,
                "msg": "success",
                "data": {"kieAudioId": "audio_abc", "name": "Narrator"},
            },
            {
                "code": "200",
                "msg": "success",
                "data": {"characterId": "character_abc"},
            },
        ]
    )

    audio = await service.create_audio(
        audio_id="Achernar",
        name="Narrator",
        voice_description="Clear voice",
        example_dialogue="Hello",
    )
    character = await service.create_character(
        description="silver hair cyberpunk character",
        image_urls=[
            "https://example.com/character.png",
            "https://example.com/extra.png",
        ],
        character_name="Jenny",
        audio_ids=["audio_abc", "audio_extra"],
    )

    assert audio["status"] == "done"
    assert audio["asset_id"] == "audio_abc"
    assert character["status"] == "done"
    assert character["asset_id"] == "character_abc"
    _, audio_payload = service._kie_post_raw.await_args_list[0].args
    _, character_payload = service._kie_post_raw.await_args_list[1].args
    assert audio_payload["audio_id"] == "achernar"
    assert character_payload["image_urls"] == ["https://example.com/character.png"]
    assert character_payload["descriptions"] == "silver hair cyberpunk character"
    assert "description" not in character_payload
    assert character_payload["audio_ids"] == ["audio_abc"]


@pytest.mark.asyncio
async def test_gemini_omni_audio_and_character_accept_async_task_ids():
    service = GeminiOmniService(kie_key="test")
    service._kie_post_raw = AsyncMock(
        side_effect=[
            {"code": 200, "msg": "success", "data": {"taskId": "audio_task"}},
            {"code": 0, "msg": "success", "data": {"task_id": "character_task"}},
        ]
    )
    service._wait_for_asset_task = AsyncMock(return_value=None)

    audio = await service.create_audio(audio_id="achernar", name="Narrator")
    character = await service.create_character(
        description="friendly hero",
        image_urls=["https://example.com/character.png"],
        character_name="Hero",
    )

    assert audio["status"] == "pending"
    assert audio["task_id"] == "audio_task"
    assert audio["asset_kind"] == "audio"
    assert character["status"] == "pending"
    assert character["task_id"] == "character_task"
    assert character["asset_kind"] == "character"
    assert service._wait_for_asset_task.await_count == 2


@pytest.mark.asyncio
async def test_gemini_omni_audio_retries_transient_system_load():
    service = GeminiOmniService(kie_key="test")
    omni_module = importlib.import_module("bot.services.gemini_omni_service")
    service._kie_post_once = AsyncMock(
        side_effect=[
            {
                "error": "api_error",
                "status_code": 500,
                "raw": {
                    "type": "error",
                    "error": {
                        "message": "The system load is too high. Please try again later."
                    },
                },
            },
            {
                "status_code": 200,
                "code": 200,
                "data": {"kieAudioId": "audio_retry"},
            },
        ]
    )

    with patch.object(omni_module.asyncio, "sleep", new=AsyncMock()):
        result = await service.create_audio(audio_id="achernar", name="Narrator")

    assert result["status"] == "done"
    assert result["asset_id"] == "audio_retry"
    assert service._kie_post_once.await_count == 2


@pytest.mark.asyncio
async def test_gemini_omni_async_audio_task_is_polled_to_asset():
    service = GeminiOmniService(kie_key="test")
    omni_module = importlib.import_module("bot.services.gemini_omni_service")
    service._kie_post_raw = AsyncMock(
        return_value={"code": 200, "data": {"taskId": "audio_task"}}
    )
    service._kie_get = AsyncMock(
        return_value={
            "code": 200,
            "data": {
                "state": "success",
                "resultJson": json.dumps(
                    {"data": {"kieAudioId": "audio_polled"}}
                ),
            },
        }
    )

    with patch.object(omni_module.asyncio, "sleep", new=AsyncMock()):
        result = await service.create_audio(audio_id="achernar", name="Narrator")

    assert result["status"] == "done"
    assert result["asset_id"] == "audio_polled"
    service._kie_get.assert_awaited_once()


def test_get_image_result_keyboard_contains_repeat_and_main_menu():
    kb = get_image_result_keyboard("https://example.com/image.png", task_id="img_123")
    button_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    callback_ids = [
        btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data
    ]
    assert "🔁 Повторить" in button_texts
    assert "repeat_image_img_123" in callback_ids
    assert "back_main" in callback_ids


def test_photo_prompt_service_detects_fast_fallback_body_500():
    assert _is_fast_fallback_application_error(
        {"code": 500, "msg": "Server exception, please try again later"}
    )
    assert _is_fast_fallback_application_error(
        {"code": 200, "msg": "Server exception, please try again later"}
    )
    assert not _is_fast_fallback_application_error({"code": 429, "msg": "rate limit"})


@pytest.mark.asyncio
async def test_photo_prompt_service_falls_back_to_claude(caplog):
    service = PhotoPromptService(api_key="test")
    service._analyze_with_gpt54 = AsyncMock(
        side_effect=RuntimeError("GPT-5.4 upstream error: 500")
    )
    service._analyze_with_claude = AsyncMock(
        return_value={
            "prompt_en": "fallback prompt",
            "prompt_ru": "резервный промпт",
            "negative_prompt": "blur",
            "model_hint": "Nano Banana Pro",
            "provider": "claude-haiku-4-5",
        }
    )

    with caplog.at_level(logging.WARNING, logger="bot.services.photo_prompt_service"):
        result = await service.analyze_photo(image_url="https://example.com/image.jpg")

    assert result["prompt_en"] == "fallback prompt"
    assert "GPT-5.4 failed" not in caplog.text
    service._analyze_with_claude.assert_awaited_once()


def test_photo_prompt_result_text_is_telegram_safe_for_long_fallback():
    result = {
        "prompt_en": "A&B " * 2000,
        "prompt_ru": "Описание & детали " * 2000,
        "negative_prompt": "bad hands, blurry, " * 500,
        "model_hint": "Nano Banana Pro " * 200,
        "provider": "claude-haiku-4-5",
    }

    text = _format_photo_prompt_result_text(result)

    assert len(text) < 4096
    assert "Fallback: claude-haiku-4-5" in text


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
