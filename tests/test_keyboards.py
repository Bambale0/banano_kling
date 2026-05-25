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
from bot.handlers.image_analyzer import (
    _audio_prompt_format,
    _clear_photo_prompt_audio_if_current,
    _format_photo_prompt_result_text,
)
import bot.services.photo_prompt_service as photo_prompt_module
from bot.services.gemini_omni_service import GeminiOmniService
from bot.services.photo_prompt_service import (
    PhotoPromptService,
    _build_gpt_user_content,
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
    assert "🖼 В ленту" in button_texts
    assert "📚 В промпты" in button_texts
    assert "grokvid_img_123" in callback_ids
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
