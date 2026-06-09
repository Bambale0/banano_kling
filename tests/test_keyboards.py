"""Unit tests for bot/keyboards.py"""

import json
import logging
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, mock_open, patch

import pytest

from bot.keyboards import (get_admin_keyboard, get_balance_keyboard,
                           get_create_hub_keyboard, get_create_video_keyboard,
                           get_help_keyboard, get_image_result_keyboard,
                           get_main_menu_keyboard,
                           get_payment_packages_keyboard,
                           get_payment_provider_keyboard, get_support_keyboard,
                           get_settings_keyboard_with_ai, get_topup_keyboard,
                           get_video_media_step_keyboard,
                           get_video_model_label,
                           get_video_model_selection_keyboard,
                           get_video_result_keyboard, get_ai_assistant_keyboard,
                           get_video_prompt_result_keyboard, load_prices)
from bot.handlers.image_analyzer import (
    _audio_prompt_format,
    _clear_photo_prompt_audio_if_current,
    _format_photo_prompt_result_text,
    _format_video_prompt_result_text,
)
from bot.handlers.generation import _normalize_video_duration_value, _repeat_image_keyboard
import bot.services.photo_prompt_service as photo_prompt_module
from bot.services.gemini_omni_service import GeminiOmniService
import bot.services.grok_service as grok_module
from bot.services.grok_service import GROK_V15_VIDEO_MODEL, GrokService
import bot.services.video_prompt_service as video_prompt_module
from bot.services.photo_prompt_service import (
    PhotoPromptService,
    SYSTEM_PROMPT,
    _build_gpt_user_content,
    _is_fast_fallback_application_error,
)
from bot.services.subscription_service import SubscriptionCheckResult
from bot.services.video_prompt_service import (
    VIDEO_SYSTEM_PROMPT,
    VideoPromptService,
    _build_gpt_video_user_content,
)
from bot.video_reference_policy import get_max_video_image_references


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


def test_get_main_menu_keyboard_hides_video_prompt_for_regular_user(monkeypatch):
    monkeypatch.setattr("bot.config.config.ADMIN_IDS_STR", "111")

    kb = get_main_menu_keyboard(10, telegram_id=222)
    callback_ids = [
        btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data
    ]

    assert "photo_to_prompt" in callback_ids
    assert "video_to_prompt" not in callback_ids


def test_get_main_menu_keyboard_shows_video_prompt_for_admin(monkeypatch):
    monkeypatch.setattr("bot.config.config.ADMIN_IDS_STR", "111")

    kb = get_main_menu_keyboard(10, telegram_id=111)
    callback_ids = [
        btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data
    ]

    assert "photo_to_prompt" in callback_ids
    assert "video_to_prompt" in callback_ids


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
    assert any(
        "admin_prompts" in btn.callback_data for row in kb.inline_keyboard for btn in row
    )
    assert any(
        "admin_ai" == btn.callback_data for row in kb.inline_keyboard for btn in row
    )
    assert any(
        "admin_ai_help" == btn.callback_data for row in kb.inline_keyboard for btn in row
    )
    assert any(
        "admin_required_subscription_toggle" == btn.callback_data
        for row in kb.inline_keyboard
        for btn in row
    )
    assert any(
        "video_to_prompt" == btn.callback_data
        for row in kb.inline_keyboard
        for btn in row
    )


def test_get_settings_keyboard_with_ai_has_referral_purchase_toggle():
    kb = get_settings_keyboard_with_ai(referral_purchase_notifications_enabled=True)
    buttons = [btn for row in kb.inline_keyboard for btn in row]

    assert any(
        btn.callback_data == "settings_ref_purchase_notify_toggle"
        and "Покупки рефералов: вкл" in btn.text
        for btn in buttons
    )

    kb = get_settings_keyboard_with_ai(referral_purchase_notifications_enabled=False)
    buttons = [btn for row in kb.inline_keyboard for btn in row]

    assert any(
        btn.callback_data == "settings_ref_purchase_notify_toggle"
        and "Покупки рефералов: выкл" in btn.text
        for btn in buttons
    )


def test_ai_assistant_keyboard_hides_admin_tools_for_regular_users(monkeypatch):
    monkeypatch.setattr("bot.config.config.ADMIN_IDS_STR", "111")

    kb = get_ai_assistant_keyboard(telegram_id=222)
    callback_ids = [
        btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data
    ]

    assert "ai_admin_help" not in callback_ids
    assert "admin_back" not in callback_ids
    assert callback_ids == ["back_main"]


def test_ai_assistant_keyboard_shows_admin_tools_only_for_admin(monkeypatch):
    monkeypatch.setattr("bot.config.config.ADMIN_IDS_STR", "111")

    kb = get_ai_assistant_keyboard(telegram_id=111)
    callback_ids = [
        btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data
    ]

    assert "ai_admin_help" in callback_ids
    assert "admin_back" in callback_ids
    assert "back_main" in callback_ids


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


def test_get_create_video_keyboard_keeps_legacy_grok_modes():
    kb = get_create_video_keyboard(current_model="grok_imagine", current_duration=6)
    callback_ids = [
        btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data
    ]
    assert "grok_mode_normal" in callback_ids
    assert "grok_mode_fun" in callback_ids
    assert "grok_mode_spicy" in callback_ids
    assert "grok_resolution_480p" not in callback_ids


def test_get_create_video_keyboard_for_grok_v15_shows_resolution_controls():
    kb = get_create_video_keyboard(
        current_model="grok_imagine_v15",
        current_ratio="auto",
        current_duration=8,
    )
    callback_ids = [
        btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data
    ]
    assert "ratio_auto" in callback_ids
    assert "ratio_4_3" in callback_ids
    assert "ratio_3_4" in callback_ids
    assert "video_dur_1" in callback_ids
    assert "video_dur_15" in callback_ids
    assert "grok_resolution_480p" in callback_ids
    assert "grok_resolution_720p" in callback_ids
    assert "grok_mode_normal" not in callback_ids


def test_grok_v15_duration_supports_one_to_fifteen_seconds():
    assert _normalize_video_duration_value("grok_imagine_v15", 1) == 1
    assert _normalize_video_duration_value("grok_imagine_v15", 16) == 15
    assert _normalize_video_duration_value("grok_imagine_v15", 8) == 8


def test_veo_duration_controls_only_show_api_supported_values():
    kb = get_create_video_keyboard(
        current_model="veo3_fast",
        current_ratio="16:9",
        current_duration=4,
    )
    callback_ids = [
        btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data
    ]

    assert "video_dur_2" not in callback_ids
    assert "video_dur_4" in callback_ids
    assert "video_dur_6" in callback_ids
    assert "video_dur_8" in callback_ids
    assert "video_dur_10" not in callback_ids


def test_veo_duration_normalizes_to_live_api_values():
    assert _normalize_video_duration_value("veo3_fast", 2) == 4
    assert _normalize_video_duration_value("veo3_lite", 10) == 8
    assert _normalize_video_duration_value("veo3", 6) == 6


def test_grok_image_reference_limits_keep_legacy_and_v15_separate():
    assert get_max_video_image_references("grok_imagine") == 7
    assert get_max_video_image_references("grok_imagine_v15") == 1


def test_miniapp_exposes_legacy_and_v15_grok_models():
    import bot.miniapp as miniapp

    models = {item["id"]: item for item in miniapp.VIDEO_MODELS}

    assert models["grok_imagine"]["grok_modes"] == ["normal", "fun", "spicy"]
    assert models["grok_imagine"]["durations"] == [6, 10, 20, 30]
    assert models["grok_imagine_v15"]["grok_resolutions"] == ["480p", "720p"]
    assert models["grok_imagine_v15"]["durations"][0] == 1
    assert models["grok_imagine_v15"]["durations"][-1] == 15


@pytest.mark.asyncio
async def test_grok_legacy_i2v_keeps_old_model_and_modes(monkeypatch):
    service = GrokService(kie_key="test-key")
    service._kie_post = AsyncMock(return_value={"task_id": "legacy_task"})
    monkeypatch.setattr(
        grok_module.kie_file_upload_service,
        "upload_local_image_sources",
        AsyncMock(return_value=["https://cdn.test/start.png", "https://cdn.test/ref.png"]),
    )

    result = await service.generate_image_to_video(
        image_urls=["https://example.test/start.jpg", "https://example.test/ref.jpg"],
        prompt="move gently",
        mode="fun",
        duration=20,
        resolution="720p",
        aspect_ratio="3:2",
        nsfw_checker=False,
    )

    assert result == {"task_id": "legacy_task"}
    payload = service._kie_post.call_args.args[1]
    assert payload["model"] == "grok-imagine/image-to-video"
    assert payload["input"]["mode"] == "fun"
    assert payload["input"]["duration"] == 20
    assert payload["input"]["image_urls"] == [
        "https://cdn.test/start.png",
        "https://cdn.test/ref.png",
    ]


@pytest.mark.asyncio
async def test_grok_v15_i2v_uses_preview_model_and_single_image(monkeypatch):
    service = GrokService(kie_key="test-key")
    service._kie_post = AsyncMock(return_value={"task_id": "v15_task"})
    monkeypatch.setattr(
        grok_module.kie_file_upload_service,
        "upload_local_image_sources",
        AsyncMock(return_value=["https://cdn.test/start.png"]),
    )

    result = await service.generate_image_to_video_v15(
        image_urls=["https://example.test/start.jpg", "https://example.test/ignored.jpg"],
        prompt="move gently",
        duration=99,
        resolution="1080p",
        aspect_ratio="bad",
        nsfw_checker=True,
    )

    assert result == {"task_id": "v15_task"}
    payload = service._kie_post.call_args.args[1]
    assert payload["model"] == GROK_V15_VIDEO_MODEL
    assert payload["input"] == {
        "prompt": "move gently",
        "image_urls": ["https://cdn.test/start.png"],
        "aspect_ratio": "auto",
        "resolution": "480p",
        "duration": 15,
        "nsfw_checker": True,
    }


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
        audio_ids=["audio_1"],
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
async def test_gemini_omni_video_rejects_multiple_video_references():
    service = GeminiOmniService(kie_key="test")
    service._kie_post = AsyncMock()

    result = await service.generate_video(
        prompt="make a city scene",
        video_list=[
            {"url": "https://example.com/a.mp4"},
            {"url": "https://example.com/b.mp4"},
        ],
    )

    assert result["error"] == "too_many_video_references"
    service._kie_post.assert_not_called()


@pytest.mark.asyncio
async def test_gemini_omni_video_rejects_over_quota_inputs():
    service = GeminiOmniService(kie_key="test")
    service._kie_post = AsyncMock()

    result = await service.generate_video(
        prompt="make a city scene",
        image_urls=[f"https://example.com/{idx}.png" for idx in range(6)],
        video_list=[{"url": "https://example.com/ref.mp4"}],
    )

    assert result["error"] == "too_many_references"
    service._kie_post.assert_not_called()


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
    assert "🎬 Оживить в Grok" in button_texts
    assert "🎬 Grok 1.5" in button_texts
    assert "🖼 В ленту" in button_texts
    assert "📚 В промпты" in button_texts
    assert "grokvid_img_123" in callback_ids
    assert "grok15vid_img_123" in callback_ids
    assert "feedpub_img_123" in callback_ids
    assert "promptsave_img_123" in callback_ids
    assert "🔁 Повторить" in button_texts
    assert "repeat_image_img_123" in callback_ids
    assert "back_main" in callback_ids


def test_get_image_result_keyboard_allows_author_removal_from_public_surfaces():
    kb = get_image_result_keyboard(
        "https://example.com/image.png",
        task_id="img_123",
        is_public_feed=True,
        is_prompt_library=True,
    )
    button_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    callback_ids = [
        btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data
    ]
    assert "🗑 Убрать из ленты" in button_texts
    assert "🗑 Убрать из промптов" in button_texts
    assert "feedrm_img_123" in callback_ids
    assert "promptrm_img_123" in callback_ids


def test_repeat_image_keyboard_edits_prompt_inside_repeat_flow():
    kb = _repeat_image_keyboard("img_123")
    callback_ids = [
        btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data
    ]

    assert "repeat_prompt_img_123" in callback_ids
    assert "retry_prompt_image_img_123" not in callback_ids


def test_get_video_result_keyboard_contains_feed_button_when_task_is_known():
    kb = get_video_result_keyboard("https://example.com/video.mp4", task_id="vid_123")
    button_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    callback_ids = [
        btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data
    ]
    assert "🎞 В ленту" in button_texts
    assert "feedpub_vid_123" in callback_ids
    assert "back_main" in callback_ids


def test_get_video_result_keyboard_allows_author_removal_from_feed():
    kb = get_video_result_keyboard(
        "https://example.com/video.mp4",
        task_id="vid_123",
        is_public_feed=True,
    )
    button_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    callback_ids = [
        btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data
    ]
    assert "🗑 Убрать из ленты" in button_texts
    assert "feedrm_vid_123" in callback_ids


def test_photo_prompt_service_detects_fast_fallback_body_500():
    assert _is_fast_fallback_application_error(
        {"code": 500, "msg": "Server exception, please try again later"}
    )
    assert _is_fast_fallback_application_error(
        {"code": 200, "msg": "Server exception, please try again later"}
    )
    assert not _is_fast_fallback_application_error({"code": 429, "msg": "rate limit"})


def test_photo_prompt_audio_mime_type_maps_to_gpt_audio_format():
    assert _audio_prompt_format("audio/mpeg") == "mp3"
    assert _audio_prompt_format("audio/x-wav") == "wav"
    assert _audio_prompt_format("audio/oga") == "ogg"
    assert _audio_prompt_format("audio/flac") == "flac"
    assert _audio_prompt_format("audio/mp4") == ""


@pytest.mark.asyncio
async def test_access_guard_blocks_unsubscribed_user(mocker):
    from bot import main as main_module
    from bot.main import AccessGuardMiddleware

    middleware = AccessGuardMiddleware()
    handler = AsyncMock(return_value="ok")
    event = SimpleNamespace(from_user=SimpleNamespace(id=777))
    bot = Mock()

    mocker.patch.object(main_module.config, "is_admin", return_value=False)
    mocker.patch("bot.main.is_user_banned", AsyncMock(return_value=False))
    mocker.patch("bot.main.is_maintenance_mode_enabled", AsyncMock(return_value=False))
    mocker.patch("bot.main.is_channel_subscription_required", AsyncMock(return_value=True))
    mocker.patch(
        "bot.main.check_required_channel_subscription",
        AsyncMock(return_value=SubscriptionCheckResult(ok=False, status="left")),
    )
    reply = AsyncMock()
    mocker.patch.object(middleware, "_reply_required_subscription", reply)

    result = await middleware(handler, event, {"bot": bot})

    assert result is None
    handler.assert_not_awaited()
    reply.assert_awaited_once_with(event)


@pytest.mark.asyncio
async def test_access_guard_blocks_unsubscribed_admin_regular_flow(mocker):
    from bot import main as main_module
    from bot.main import AccessGuardMiddleware

    middleware = AccessGuardMiddleware()
    handler = AsyncMock(return_value="ok")
    event = SimpleNamespace(from_user=SimpleNamespace(id=777), data="create_image_text_new")
    bot = Mock()

    mocker.patch.object(main_module.config, "is_admin", return_value=True)
    mocker.patch("bot.main.is_user_banned", AsyncMock(return_value=False))
    mocker.patch("bot.main.is_maintenance_mode_enabled", AsyncMock(return_value=False))
    mocker.patch("bot.main.is_channel_subscription_required", AsyncMock(return_value=True))
    subscription_check = mocker.patch(
        "bot.main.check_required_channel_subscription",
        AsyncMock(return_value=SubscriptionCheckResult(ok=False, status="left")),
    )
    reply = AsyncMock()
    mocker.patch.object(middleware, "_reply_required_subscription", reply)

    result = await middleware(handler, event, {"bot": bot})

    assert result is None
    handler.assert_not_awaited()
    subscription_check.assert_awaited_once_with(bot, 777)
    reply.assert_awaited_once_with(event)


@pytest.mark.asyncio
async def test_access_guard_allows_admin_management_without_subscription(mocker):
    from bot import main as main_module
    from bot.main import AccessGuardMiddleware

    middleware = AccessGuardMiddleware()
    handler = AsyncMock(return_value="ok")
    event = SimpleNamespace(
        from_user=SimpleNamespace(id=777),
        data="admin_required_subscription_toggle",
    )
    bot = Mock()
    data = {"bot": bot}

    mocker.patch.object(main_module.config, "is_admin", return_value=True)
    mocker.patch("bot.main.is_user_banned", AsyncMock(return_value=False))
    mocker.patch("bot.main.is_maintenance_mode_enabled", AsyncMock(return_value=False))
    subscription_required = mocker.patch(
        "bot.main.is_channel_subscription_required",
        AsyncMock(return_value=True),
    )
    subscription_check = mocker.patch(
        "bot.main.check_required_channel_subscription",
        AsyncMock(return_value=SubscriptionCheckResult(ok=False, status="left")),
    )

    result = await middleware(handler, event, data)

    assert result == "ok"
    handler.assert_awaited_once_with(event, data)
    subscription_required.assert_not_awaited()
    subscription_check.assert_not_awaited()


def test_photo_prompt_system_prompt_prefers_editorial_russian_style():
    assert '"prompt_ru" is the main result' in SYSTEM_PROMPT
    assert "one natural, dense editorial/photo prompt" in SYSTEM_PROMPT
    assert "900-1600 characters" in SYSTEM_PROMPT
    assert "Do not use forensic" in SYSTEM_PROMPT


def test_video_prompt_system_prompt_prefers_cinematic_russian_style():
    assert '"prompt_ru" is the main result' in VIDEO_SYSTEM_PROMPT
    assert "photorealistic AI video generation" in VIDEO_SYSTEM_PROMPT
    assert "camera movement" in VIDEO_SYSTEM_PROMPT
    assert "Return only valid JSON" in VIDEO_SYSTEM_PROMPT


def test_video_prompt_user_content_passes_video_as_input_file():
    content = _build_gpt_video_user_content(
        user_instruction="Analyze video",
        video_url="https://example.com/reference.mp4",
        filename="reference.mp4",
    )

    assert content == [
        {"type": "input_text", "text": "Analyze video"},
        {
            "type": "input_file",
            "file_url": "https://example.com/reference.mp4",
            "filename": "reference.mp4",
        },
    ]


@pytest.mark.asyncio
async def test_video_prompt_service_passes_video_file_to_gpt55():
    service = VideoPromptService(api_key="test")
    captured = {}

    async def fake_gpt55(**kwargs):
        captured.update(kwargs)
        return {
            "prompt_en": "A cinematic tracking shot",
            "prompt_ru": "Кинематографичный трекинговый кадр",
            "negative_prompt": "flicker",
            "camera_movement_ru": "Плавный трекинг",
            "timeline_ru": ["Стартовый средний план", "Плавное движение камеры"],
            "visual_style_ru": "Мягкий контрастный свет",
            "model_hint": "Gemini Omni Video",
            "provider": "gpt-5.5",
        }

    service._analyze_with_gpt55 = AsyncMock(side_effect=fake_gpt55)

    result = await service.analyze_video(
        video_url="https://example.com/reference.mp4",
        user_note="Сделай более модный свет",
        duration_seconds=7,
        filename="reference.mp4",
    )

    assert captured["video_url"] == "https://example.com/reference.mp4"
    assert captured["filename"] == "reference.mp4"
    assert "Additional text instruction from user" in captured["user_instruction"]
    assert "7 seconds" in captured["user_instruction"]
    assert result["camera_movement_ru"] == "Плавный трекинг"


@pytest.mark.asyncio
async def test_video_prompt_gpt55_payload_uses_input_file(monkeypatch):
    responses = [
        {
            "status": 200,
            "body": {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "text": json.dumps(
                                    {
                                        "prompt_en": "Tracking shot",
                                        "prompt_ru": "Плавный трекинговый кадр",
                                        "negative_prompt": "flicker",
                                        "model_hint": "Gemini Omni Video",
                                    }
                                )
                            }
                        ],
                    }
                ]
            },
        }
    ]
    payloads = []

    class FakeResponse:
        def __init__(self, item):
            self.status = item["status"]
            self._text = json.dumps(item["body"])

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self):
            return self._text

    class FakeSession:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None, headers=None):
            payloads.append(json)
            return FakeResponse(responses.pop(0))

    monkeypatch.setattr(video_prompt_module.aiohttp, "ClientSession", FakeSession)

    service = VideoPromptService(api_key="test")
    result = await service._analyze_with_gpt55(
        video_url="https://example.com/reference.mp4",
        user_instruction="Analyze video",
        headers={"Authorization": "Bearer test"},
        filename="reference.mp4",
    )

    assert result["prompt_ru"] == "Плавный трекинговый кадр"
    assert [
        item["type"] for item in payloads[-1]["input"][1]["content"]
    ] == ["input_text", "input_file"]
    assert payloads[-1]["input"][1]["content"][1]["file_url"] == (
        "https://example.com/reference.mp4"
    )


def test_video_prompt_result_text_is_telegram_safe_for_long_result():
    result = {
        "prompt_en": "A&B cinematic movement " * 500,
        "prompt_ru": "Кинематографичное движение и модный свет " * 500,
        "negative_prompt": "flicker, jitter, " * 300,
        "camera_movement_ru": "Плавный трекинг камеры " * 80,
        "timeline_ru": ["Камера движется плавно " * 80] * 6,
        "visual_style_ru": "Неоновый контрастный свет " * 80,
        "audio_notes_ru": "Музыка и шум пространства " * 80,
        "model_hint": "Gemini Omni Video " * 100,
        "provider": "gpt-5.5",
    }

    text = _format_video_prompt_result_text(result)

    assert len(text) < 4096
    assert "Промпт по видео готов" in text
    assert "Negative prompt" in text


def test_video_prompt_result_keyboard_restarts_video_prompt_flow():
    kb = get_video_prompt_result_keyboard()
    callback_ids = [
        btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data
    ]

    assert callback_ids == ["video_to_prompt", "back_main"]


def test_photo_prompt_gpt_user_content_attaches_audio_and_image():
    content = _build_gpt_user_content(
        user_instruction="Analyze photo and voice",
        image_url="https://example.com/image.jpg",
        audio_bytes=b"voice-bytes",
        audio_format="ogg",
    )

    assert content[0] == {
        "type": "input_text",
        "text": "Analyze photo and voice",
    }
    assert content[1] == {
        "type": "input_image",
        "image_url": "https://example.com/image.jpg",
    }
    assert content[2]["type"] == "input_audio"
    assert content[2]["input_audio"]["format"] == "ogg"
    assert content[2]["input_audio"]["data"]


def test_photo_prompt_gpt_user_content_allows_audio_without_image():
    content = _build_gpt_user_content(
        user_instruction="Analyze voice",
        image_url="",
        audio_bytes=b"voice-bytes",
        audio_format="ogg",
    )

    assert content[0] == {
        "type": "input_text",
        "text": "Analyze voice",
    }
    assert [item["type"] for item in content] == ["input_text", "input_audio"]
    assert content[1]["input_audio"]["format"] == "ogg"
    assert content[1]["input_audio"]["data"]


@pytest.mark.asyncio
async def test_photo_prompt_service_falls_back_to_claude(caplog):
    service = PhotoPromptService(api_key="test")
    service._analyze_with_gpt55 = AsyncMock(
        side_effect=RuntimeError("GPT-5.5 upstream error: 500")
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
    assert "GPT-5.5 failed" not in caplog.text
    service._analyze_with_claude.assert_awaited_once()


@pytest.mark.asyncio
async def test_photo_prompt_service_passes_audio_to_gpt55_without_claude():
    service = PhotoPromptService(api_key="test")
    captured = {}

    async def fake_gpt55(**kwargs):
        captured["user_instruction"] = kwargs["user_instruction"]
        captured["audio_bytes"] = kwargs["audio_bytes"]
        captured["audio_format"] = kwargs["audio_format"]
        return {
            "prompt_en": "A detailed cinematic portrait",
            "prompt_ru": "Детальный кинематографичный портрет",
            "negative_prompt": "blur",
            "model_hint": "Gemini Omni для видео-версии",
            "voice_transcript": "Сделай плавный наезд камеры",
            "voice_prompt_summary_ru": "Плавный наезд камеры к объекту",
            "voice_description_ru": "Уверенный спокойный голос",
            "gemini_omni_prompt": "Slow cinematic push-in toward the subject.",
            "provider": "gpt-5.5",
        }

    service._analyze_with_gpt55 = AsyncMock(side_effect=fake_gpt55)
    service._analyze_with_claude = AsyncMock()

    result = await service.analyze_photo(
        image_url="https://example.com/image.jpg",
        user_note="Больше драматичного света",
        audio_bytes=b"voice-bytes",
        audio_format="ogg",
    )

    assert "Additional text instruction from user" in captured["user_instruction"]
    assert "Attached audio prompt" in captured["user_instruction"]
    assert captured["audio_bytes"] == b"voice-bytes"
    assert captured["audio_format"] == "ogg"
    assert result["voice_prompt_summary_ru"] == "Плавный наезд камеры к объекту"
    assert result["voice_description_ru"] == "Уверенный спокойный голос"
    assert result["gemini_omni_prompt"] == "Slow cinematic push-in toward the subject."
    service._analyze_with_claude.assert_not_awaited()


@pytest.mark.asyncio
async def test_photo_prompt_service_passes_audio_without_image_to_gpt55():
    service = PhotoPromptService(api_key="test")
    captured = {}

    async def fake_gpt55(**kwargs):
        captured["image_url"] = kwargs["image_url"]
        captured["user_instruction"] = kwargs["user_instruction"]
        captured["audio_bytes"] = kwargs["audio_bytes"]
        captured["audio_format"] = kwargs["audio_format"]
        return {
            "prompt_en": "A cinematic city scene from a spoken prompt",
            "prompt_ru": "Кинематографичная городская сцена по голосу",
            "negative_prompt": "blur",
            "model_hint": "Gemini Omni",
            "voice_transcript": "Сделай ночной город с плавной камерой",
            "voice_prompt_summary_ru": "Ночной город и плавное движение камеры",
            "voice_description_ru": "Спокойный голос",
            "gemini_omni_prompt": "Night city with a smooth camera move.",
            "provider": "gpt-5.5",
        }

    service._analyze_with_gpt55 = AsyncMock(side_effect=fake_gpt55)
    service._analyze_with_claude = AsyncMock()

    result = await service.analyze_photo(
        image_url="   ",
        audio_bytes=b"voice-bytes",
        audio_format="ogg",
    )

    assert captured["image_url"] == ""
    assert "Listen to the attached audio prompt" in captured["user_instruction"]
    assert captured["audio_bytes"] == b"voice-bytes"
    assert captured["audio_format"] == "ogg"
    assert result["voice_transcript"] == "Сделай ночной город с плавной камерой"
    service._analyze_with_claude.assert_not_awaited()


@pytest.mark.asyncio
async def test_photo_prompt_service_requires_image_or_audio():
    service = PhotoPromptService(api_key="test")

    with pytest.raises(ValueError, match="image_url or audio_bytes"):
        await service.analyze_photo(image_url="")


@pytest.mark.asyncio
async def test_photo_prompt_gpt55_retries_audio_application_500(monkeypatch):
    responses = [
        {
            "status": 200,
            "body": {
                "code": 500,
                "msg": "Server exception, please try again later",
            },
        },
        {
            "status": 200,
            "body": {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "text": json.dumps(
                                    {
                                        "prompt_en": "Recovered audio prompt",
                                        "prompt_ru": "Голосовой промпт восстановлен",
                                        "negative_prompt": "blur",
                                        "model_hint": "Gemini Omni",
                                    }
                                )
                            }
                        ],
                    }
                ]
            },
        },
    ]
    payloads = []

    class FakeResponse:
        def __init__(self, item):
            self.status = item["status"]
            self._text = json.dumps(item["body"])

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self):
            return self._text

    class FakeSession:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None, headers=None):
            payloads.append(json)
            return FakeResponse(responses.pop(0))

    monkeypatch.setattr(photo_prompt_module.aiohttp, "ClientSession", FakeSession)
    monkeypatch.setattr(photo_prompt_module.asyncio, "sleep", AsyncMock())

    service = PhotoPromptService(api_key="test")
    result = await service._analyze_with_gpt55(
        image_url="",
        user_instruction="Analyze voice",
        headers={"Authorization": "Bearer test"},
        audio_bytes=b"voice-bytes",
        audio_format="ogg",
    )

    assert result["prompt_en"] == "Recovered audio prompt"
    assert len(payloads) == 2
    assert [
        item["type"] for item in payloads[-1]["input"][1]["content"]
    ] == ["input_text", "input_audio"]


@pytest.mark.asyncio
async def test_photo_prompt_service_does_not_drop_audio_to_claude_fallback():
    service = PhotoPromptService(api_key="test")
    service._analyze_with_gpt55 = AsyncMock(
        side_effect=RuntimeError("GPT-5.5 audio unsupported")
    )
    service._analyze_with_claude = AsyncMock()

    with pytest.raises(RuntimeError, match="фото и голос"):
        await service.analyze_photo(
            image_url="https://example.com/image.jpg",
            audio_bytes=b"voice-bytes",
            audio_format="ogg",
        )

    service._analyze_with_claude.assert_not_awaited()


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


def test_photo_prompt_result_text_with_voice_context_stays_telegram_safe():
    result = {
        "prompt_en": "A&B " * 2000,
        "prompt_ru": "Описание & детали " * 2000,
        "negative_prompt": "bad hands, blurry, " * 500,
        "model_hint": "Gemini Omni " * 200,
        "voice_prompt_summary_ru": "Пользователь попросил киношный кадр " * 200,
        "voice_description_ru": "Спокойный голос " * 200,
        "gemini_omni_prompt": "Slow cinematic camera move " * 200,
        "provider": "claude-haiku-4-5",
    }

    text = _format_photo_prompt_result_text(result)

    assert len(text) < 4096
    assert "Учтён голосовой промпт" in text
    assert "Gemini Omni prompt" in text


def test_photo_prompt_result_text_uses_voice_title():
    result = {
        "prompt_en": "Prompt",
        "prompt_ru": "Промпт",
        "negative_prompt": "blur",
        "model_hint": "Gemini Omni",
        "source_mode": "voice",
    }

    text = _format_photo_prompt_result_text(result)

    assert "Промпт по голосу готов" in text


class DummyPhotoPromptState:
    def __init__(self, data):
        self.data = dict(data)

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)


@pytest.mark.asyncio
async def test_photo_prompt_clear_failed_voice_removes_current_audio():
    state = DummyPhotoPromptState(
        {
            "photo_prompt_audio_pending": "voice-1",
            "photo_prompt_audio": {"url": "/uploads/voice.ogg"},
        }
    )

    await _clear_photo_prompt_audio_if_current(
        state,
        audio_url="/uploads/voice.ogg",
        pending_token="voice-1",
    )

    assert state.data["photo_prompt_audio_pending"] is None
    assert state.data["photo_prompt_audio"] is None


@pytest.mark.asyncio
async def test_photo_prompt_clear_failed_voice_keeps_consumed_audio():
    state = DummyPhotoPromptState(
        {
            "photo_prompt_audio_pending": "voice-1",
            "photo_prompt_audio": {"url": "/uploads/voice.ogg"},
            "photo_prompt_audio_consumed_url": "/uploads/voice.ogg",
        }
    )

    await _clear_photo_prompt_audio_if_current(
        state,
        audio_url="/uploads/voice.ogg",
        pending_token="voice-1",
    )

    assert state.data["photo_prompt_audio_pending"] is None
    assert state.data["photo_prompt_audio"] == {"url": "/uploads/voice.ogg"}


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
