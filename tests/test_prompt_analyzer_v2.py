from unittest.mock import AsyncMock

import pytest

from bot.handlers import image_analyzer_router, prompt_analyzer_v2_router
from bot.handlers.prompt_analyzer_v2 import (
    _format_prompt_result_text,
    _send_prompt_result,
)
from bot.services.prompt_analyzer_v2_service import (
    PromptAnalyzerV2Service,
    _build_gpt_user_content,
    _build_result,
)


def test_unified_prompt_analyzer_is_registered_before_legacy_router():
    assert image_analyzer_router.sub_routers[0] is prompt_analyzer_v2_router


def test_result_contains_only_bilingual_prompt_fields():
    result = _build_result(
        {
            "prompt_ru": "Русский промпт",
            "prompt_en": "English prompt",
            "negative_prompt": "must be ignored",
            "model_hint": "must be ignored",
            "gemini_omni_prompt": "must be ignored",
        },
        provider="gpt-5.5",
    )

    assert result["prompt_ru"] == "Русский промпт"
    assert result["prompt_en"] == "English prompt"
    assert "negative_prompt" not in result
    assert "model_hint" not in result
    assert "gemini_omni_prompt" not in result


def test_formatter_does_not_show_removed_sections():
    text = _format_prompt_result_text(
        {
            "prompt_ru": "Русский промпт",
            "prompt_en": "English prompt",
            "source_mode": "text",
        }
    )

    assert "Русская версия" in text
    assert "English version" in text
    assert "Negative prompt" not in text
    assert "Рекомендация" not in text
    assert "Gemini Omni" not in text


@pytest.mark.asyncio
async def test_sender_attaches_full_unclipped_prompt_file():
    message = AsyncMock()
    prompt_ru = "Подробное описание & детали " * 200
    prompt_en = "Detailed description & features " * 200

    await _send_prompt_result(
        message,
        {
            "prompt_ru": prompt_ru,
            "prompt_en": prompt_en,
            "source_mode": "photo",
        },
    )

    message.answer.assert_awaited_once()
    message.answer_document.assert_awaited_once()
    document = message.answer_document.await_args.kwargs["document"]
    contents = document.data.decode("utf-8")
    assert document.filename == "photo_prompt_full.txt"
    assert prompt_ru.strip() in contents
    assert prompt_en.strip() in contents
    assert "…" not in contents


def test_system_prompt_requests_complete_photo_reconstruction():
    from bot.services.prompt_analyzer_v2_service import SYSTEM_PROMPT

    assert "Prefer completeness over brevity" in SYSTEM_PROMPT
    assert "900-1800 characters per language" in SYSTEM_PROMPT
    assert "facial features without identifying the person" in SYSTEM_PROMPT


def test_gpt_content_supports_text_image_and_audio_together():
    content = _build_gpt_user_content(
        user_instruction="Create a prompt",
        image_url="https://example.test/reference.jpg",
        audio_bytes=b"voice",
        audio_format="ogg",
    )

    assert [item["type"] for item in content] == [
        "input_text",
        "input_image",
        "input_audio",
    ]


@pytest.mark.asyncio
async def test_analyzer_rejects_empty_input():
    service = PromptAnalyzerV2Service(api_key="test-key")

    with pytest.raises(ValueError, match="text, image_url or audio_bytes"):
        await service.analyze_prompt()
