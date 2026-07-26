from bot.services import photo_prompt_service


def test_telegram_photo_prompt_uses_vk_reconstruction_instruction() -> None:
    prompt = photo_prompt_service.SYSTEM_PROMPT

    assert "Составь подробный промпт для создания максимально похожего фото в Banana Pro" in prompt
    assert "Сохрани все мелкие детали, лицо, одежду, позу, освещение, стиль, цвета" in prompt
    assert "Ты эксперт по промптам для генерации изображений" in prompt
    assert "Верни только валидный JSON" in prompt


def test_vk_compat_keeps_legacy_structured_fields_without_omni() -> None:
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

    assert '"gemini_omni_prompt"' not in prompt


def test_vk_compat_does_not_wrap_analyze_photo() -> None:
    assert photo_prompt_service.PhotoPromptService.analyze_photo.__name__ == "analyze_photo"
