from unittest.mock import AsyncMock

import pytest

import bot.services.photo_prompt_service as photo_module
import bot.services.prompt_analyzer_v2_service as v2_module
import bot.services.video_prompt_service as video_module
from bot.services.photo_prompt_service import PhotoPromptService
from bot.services.prompt_analyzer_v2_service import PromptAnalyzerV2Service
from bot.services.video_prompt_service import VideoPromptService

PHOTO_JSON = '{"prompt_ru":"Русский промпт","prompt_en":"English prompt"}'
RICH_PHOTO_JSON = (
    '{"prompt_ru":"Русский промпт","prompt_en":"English prompt",'
    '"negative_prompt":"blur","model_hint":"Nano Banana Pro","key_details":[]}'
)
VIDEO_JSON = (
    '{"prompt_ru":"Русское видео","prompt_en":"English video",'
    '"negative_prompt":"flicker","camera_movement_ru":"Трекинг",'
    '"timeline_ru":["Начало","Финал"],"visual_style_ru":"Кино",'
    '"audio_notes_ru":"","model_hint":"Kling","key_details":[]}'
)


@pytest.mark.asyncio
async def test_unified_photo_prompt_uses_qwen38_before_kie(monkeypatch) -> None:
    qwen = v2_module.comet_qwen38_service
    monkeypatch.setattr(qwen, "enabled", True)
    monkeypatch.setattr(qwen, "model", "qwen3.8-max")
    monkeypatch.setattr(qwen, "analyze_image", AsyncMock(return_value=PHOTO_JSON))

    service = PromptAnalyzerV2Service(api_key="kie-fallback-key")
    service._analyze_with_gpt55 = AsyncMock()

    result = await service.analyze_prompt(image_url="https://example.test/photo.jpg")

    assert result["provider"] == "qwen3.8-max"
    qwen.analyze_image.assert_awaited_once()
    service._analyze_with_gpt55.assert_not_awaited()


@pytest.mark.asyncio
async def test_unified_photo_prompt_falls_back_to_kie_after_qwen_failure(monkeypatch) -> None:
    qwen = v2_module.comet_qwen38_service
    monkeypatch.setattr(qwen, "enabled", True)
    monkeypatch.setattr(qwen, "analyze_image", AsyncMock(side_effect=RuntimeError("Comet down")))

    service = PromptAnalyzerV2Service(api_key="kie-fallback-key")
    service._analyze_with_gpt55 = AsyncMock(
        return_value={
            "prompt_ru": "fallback ru",
            "prompt_en": "fallback en",
            "provider": "gpt-5.5",
            "raw": {},
        }
    )

    result = await service.analyze_prompt(image_url="https://example.test/photo.jpg")

    assert result["provider"] == "gpt-5.5"
    qwen.analyze_image.assert_awaited_once()
    service._analyze_with_gpt55.assert_awaited_once()


@pytest.mark.asyncio
async def test_photo_service_uses_qwen38_for_image_only(monkeypatch) -> None:
    qwen = photo_module.comet_qwen38_service
    monkeypatch.setattr(qwen, "enabled", True)
    monkeypatch.setattr(qwen, "analyze_image", AsyncMock(return_value=RICH_PHOTO_JSON))
    monkeypatch.setattr(photo_module, "image_source_to_analysis_input", lambda value: value)

    service = PhotoPromptService(api_key="kie-fallback-key")
    service._analyze_with_gpt55 = AsyncMock()

    result = await service.analyze_photo(image_url="https://example.test/photo.jpg")

    assert result["prompt_ru"] == "Русский промпт"
    assert result["provider"] == ""
    qwen.analyze_image.assert_awaited_once()
    service._analyze_with_gpt55.assert_not_awaited()


@pytest.mark.asyncio
async def test_photo_plus_audio_stays_on_existing_audio_pipeline(monkeypatch) -> None:
    qwen = photo_module.comet_qwen38_service
    monkeypatch.setattr(qwen, "enabled", True)
    monkeypatch.setattr(qwen, "analyze_image", AsyncMock())
    monkeypatch.setattr(photo_module, "image_source_to_analysis_input", lambda value: value)

    service = PhotoPromptService(api_key="kie-key")
    service._analyze_with_gpt55 = AsyncMock(
        return_value={
            "prompt_ru": "audio ru",
            "prompt_en": "audio en",
            "negative_prompt": "",
            "provider": "",
            "raw": {},
        }
    )

    await service.analyze_photo(
        image_url="https://example.test/photo.jpg",
        audio_bytes=b"voice",
        audio_format="ogg",
    )

    qwen.analyze_image.assert_not_awaited()
    service._analyze_with_gpt55.assert_awaited_once()


@pytest.mark.asyncio
async def test_video_prompt_uses_qwen38_before_kie(monkeypatch) -> None:
    qwen = video_module.comet_qwen38_service
    monkeypatch.setattr(qwen, "enabled", True)
    monkeypatch.setattr(qwen, "model", "qwen3.8-max")
    monkeypatch.setattr(qwen, "analyze_video", AsyncMock(return_value=VIDEO_JSON))

    service = VideoPromptService(api_key="kie-fallback-key")
    service._analyze_with_gpt55 = AsyncMock()
    service._analyze_frames_with_gpt55 = AsyncMock()

    result = await service.analyze_video(
        video_url="https://example.test/clip.mp4",
        duration_seconds=12,
    )

    assert result["provider"] == "qwen3.8-max"
    assert result["camera_movement_ru"] == "Трекинг"
    qwen.analyze_video.assert_awaited_once()
    service._analyze_with_gpt55.assert_not_awaited()
    service._analyze_frames_with_gpt55.assert_not_awaited()
