from bot.services import photo_prompt_service
from bot.services.photo_prompt_vk_compat import _strip_gemini_omni_prompt


def test_telegram_photo_prompt_uses_vk_reconstruction_instruction() -> None:
    prompt = photo_prompt_service.SYSTEM_PROMPT

    assert "Составь подробный промпт для создания максимально похожего фото в Banana Pro" in prompt
    assert "Сохрани все мелкие детали, лицо, одежду, позу, освещение, стиль, цвета" in prompt
    assert "Ты эксперт по промптам для генерации изображений" in prompt
    assert "Верни только валидный JSON" in prompt


def test_vk_compat_keeps_telegram_structured_fields_without_omni() -> None:
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


def test_vk_compat_strips_omni_from_result_and_raw_payload() -> None:
    result = _strip_gemini_omni_prompt(
        {
            "prompt_ru": "Промпт",
            "gemini_omni_prompt": "Удалить",
            "raw": {
                "prompt_ru": "Промпт",
                "gemini_omni_prompt": "Тоже удалить",
            },
        }
    )

    assert "gemini_omni_prompt" not in result
    assert "gemini_omni_prompt" not in result["raw"]
