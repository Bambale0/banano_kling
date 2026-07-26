"""Align Telegram photo analysis instructions with the proven VK prompt.

Only the internal analysis prompt is changed. The existing Telegram response
shape, handlers and user-facing UX remain untouched.
"""
from __future__ import annotations


VK_PHOTO_ANALYSIS_PROMPT = (
    "Составь подробный промпт для создания максимально похожего фото в Banana Pro. "
    "Сохрани все мелкие детали, лицо, одежду, позу, освещение, стиль, цвета. "
    "На русском языке."
)

VK_PHOTO_ANALYSIS_INSTRUCTIONS = (
    "Ты эксперт по промптам для генерации изображений. "
    "Отвечай готовым результатом без вводных фраз."
)


def install_vk_photo_prompt_instructions() -> None:
    """Patch only the analyzer prompt while preserving the legacy UX contract."""
    from bot.services import photo_prompt_service as module

    if getattr(module, "_vk_photo_prompt_instructions_installed", False):
        return

    module.SYSTEM_PROMPT = f"""
{VK_PHOTO_ANALYSIS_INSTRUCTIONS}

Главная задача для анализа фотографии:
{VK_PHOTO_ANALYSIS_PROMPT}

Правила результата:
- Максимально точно передай видимые детали исходного изображения.
- Особое внимание удели лицу и внешности без установления личности: форма лица,
  черты, выражение, волосы, макияж и видимые особенности.
- Подробно сохрани одежду, материалы, фактуры, аксессуары, позу и направление взгляда.
- Точно опиши композицию, крупность кадра, ракурс, фон, освещение, тени,
  цветовую палитру, контраст, настроение и визуальный стиль.
- Не сокращай описание до общих слов и не заменяй видимые детали шаблонными
  выражениями вроде masterpiece, 8K или best quality.
- Основное поле prompt_ru должно быть готовым цельным русским промптом для
  создания максимально похожего изображения в Banana Pro.
- prompt_en должен быть точным английским переводом prompt_ru.
- Если пользователь приложил голос или дополнительную инструкцию, аккуратно
  совмести её с фотографией, не теряя детали исходника.
- Не создавай Gemini Omni prompt и не включай поле gemini_omni_prompt.
- Не идентифицируй человека, не называй имя, национальность, этничность,
  медицинские или иные чувствительные характеристики.
- Верни только валидный JSON без markdown и пояснений.

JSON schema:
{{
  "prompt_en": "Detailed English image generation prompt",
  "prompt_ru": "Подробный русский промпт для максимально похожего фото в Banana Pro",
  "negative_prompt": "Common defects to avoid",
  "model_hint": "Short Russian recommendation which model to use",
  "key_details": ["detail 1", "detail 2", "detail 3"],
  "voice_transcript": "Transcript of attached voice/audio prompt, or empty string",
  "voice_prompt_summary_ru": "Short Russian summary of the attached voice/audio prompt, or empty string",
  "voice_description_ru": "Neutral Russian description of voice/tone/pace/emotion, or empty string"
}}
""".strip()

    module._vk_photo_prompt_instructions_installed = True
