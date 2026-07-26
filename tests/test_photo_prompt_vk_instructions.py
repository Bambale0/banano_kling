from bot.services import photo_prompt_service


def test_telegram_photo_prompt_uses_vk_reconstruction_instruction() -> None:
    prompt = photo_prompt_service.SYSTEM_PROMPT

    assert "Составь подробный промпт для создания максимально похожего фото в Banana Pro" in prompt
    assert "Сохрани все мелкие детали, лицо, одежду, позу, освещение, стиль, цвета" in prompt
    assert "Ты эксперт по промптам для генерации изображений" in prompt
    assert "Верни только валидный JSON" in prompt


def test_vk_compat_keeps_telegram_structured_fields() -> None:
    prompt = photo_prompt_service.SYSTEM_PROMPT

    for field in (
        '"prompt_en"',
        '"prompt_ru"',
        '"negative_prompt"',
        '"model_hint"',
        '"key_details"',
        '"voice_transcript"',
        '"gemini_omni_prompt"',
    ):
        assert field in prompt
