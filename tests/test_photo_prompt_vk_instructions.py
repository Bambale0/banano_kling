from bot.services import photo_prompt_service


def test_telegram_photo_prompt_uses_vk_reconstruction_instruction() -> None:
    prompt = photo_prompt_service.SYSTEM_PROMPT

    assert "senior prompt analyst for photorealistic AI image generation" in prompt
    assert 'The user-facing "prompt_ru" is the main result' in prompt
    assert "Return only valid JSON" in prompt


def test_photo_prompt_keeps_structured_fields_with_omni() -> None:
    prompt = photo_prompt_service.SYSTEM_PROMPT

    for field in (
        '"prompt_en"',
        '"prompt_ru"',
        '"negative_prompt"',
        '"model_hint"',
        '"key_details"',
        '"voice_transcript"',
    ):
        assert field in prompt

    assert '"gemini_omni_prompt"' in prompt


def test_vk_compat_does_not_wrap_analyze_photo() -> None:
    assert photo_prompt_service.PhotoPromptService.analyze_photo.__name__ == "analyze_photo"
