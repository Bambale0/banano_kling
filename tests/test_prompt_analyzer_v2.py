import pytest

from bot.handlers.prompt_analyzer_v2 import _format_prompt_result_text
from bot.services.prompt_analyzer_v2_service import (
    PromptAnalyzerV2Service,
    _build_gpt_user_content,
    _build_result,
)


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
