"""Align Telegram photo analysis instructions with the proven VK prompt.

The Telegram service keeps its structured RU/EN output, negative prompt,
model hints, voice support and provider fallbacks. Gemini Omni-specific output
is deliberately excluded from the photo-analysis contract.
"""
from __future__ import annotations

from functools import wraps
from typing import Any


VK_PHOTO_ANALYSIS_PROMPT = (
    "Составь подробный промпт для создания максимально похожего фото в Banana Pro. "
    "Сохрани все мелкие детали, лицо, одежду, позу, освещение, стиль, цвета. "
    "На русском языке."
)

VK_PHOTO_ANALYSIS_INSTRUCTIONS = (
    "Ты эксперт по промптам для генерации изображений. "
    "Отвечай готовым результатом без вводных фраз."
)


def _strip_gemini_omni_prompt(result: Any) -> Any:
    """Remove obsolete Omni-specific data from photo-analysis responses."""
    if not isinstance(result, dict):
        return result

    cleaned = dict(result)
    cleaned.pop("gemini_omni_prompt", None)

    raw = cleaned.get("raw")
    if isinstance(raw, dict):
        raw_cleaned = dict(raw)
        raw_cleaned.pop("gemini_omni_prompt", None)
        cleaned["raw"] = raw_cleaned

    return cleaned


def install_vk_photo_prompt_instructions() -> None:
    """Patch photo analysis once and exclude Gemini Omni-specific output."""
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

    original_analyze_photo = module.PhotoPromptService.analyze_photo

    @wraps(original_analyze_photo)
    async def analyze_photo_without_gemini_omni(self, *args, **kwargs):
        result = await original_analyze_photo(self, *args, **kwargs)
        return _strip_gemini_omni_prompt(result)

    module.PhotoPromptService.analyze_photo = analyze_photo_without_gemini_omni
    module._vk_photo_prompt_instructions_installed = True
