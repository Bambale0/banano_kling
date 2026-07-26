"""VK-compatible result layout for Telegram photo-only prompt analysis.

The established Telegram photo/voice workflow remains untouched. Ordinary photo-only
analysis returns the same compact result structure as the VK bot: one ready Russian
prompt followed by a short usage hint.
"""

from __future__ import annotations

import importlib
from functools import wraps
from typing import Any

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
VK_PROMPT_SOFT_LIMIT = 3800

_RESULT_HEADER = "✅ Готовый промпт:\n\n"
_RESULT_FOOTER = (
    "\n\nКак использовать: скопируйте текст и вставьте его в экран «Создать фото» "
    "или «Создать видео». При необходимости добавьте свои правки: формат, "
    "настроение, цвет, действие."
)
_TRIMMED_FOOTER = (
    "\n\n⚠️ Промпт был обрезан до лимита Telegram. Его можно вставить в «Создать фото» "
    "или «Создать видео».\nПри необходимости добавьте свои правки: формат, "
    "настроение, цвет, действие."
)


def _trim_prompt(prompt: str, max_len: int) -> tuple[str, bool]:
    value = str(prompt or "").strip()
    if len(value) <= max_len:
        return value, False

    trimmed = value[:max_len]
    last_space = trimmed.rfind(" ")
    if last_space > max_len // 2:
        trimmed = trimmed[:last_space]
    return trimmed.rstrip() + "…", True


def format_vk_photo_prompt_result(prompt: str) -> tuple[str, bool]:
    """Return the VK-style Telegram result and whether the prompt was trimmed."""

    value = str(prompt or "").strip()
    normal_budget = min(
        VK_PROMPT_SOFT_LIMIT,
        TELEGRAM_MAX_MESSAGE_LENGTH - len(_RESULT_HEADER) - len(_RESULT_FOOTER),
    )
    trimmed_value, was_trimmed = _trim_prompt(value, normal_budget)

    if not was_trimmed:
        return f"{_RESULT_HEADER}{trimmed_value}{_RESULT_FOOTER}", False

    trimmed_budget = min(
        VK_PROMPT_SOFT_LIMIT,
        TELEGRAM_MAX_MESSAGE_LENGTH - len(_RESULT_HEADER) - len(_TRIMMED_FOOTER),
    )
    trimmed_value, _ = _trim_prompt(value, trimmed_budget)
    return f"{_RESULT_HEADER}{trimmed_value}{_TRIMMED_FOOTER}", True


def _prompt_from_result(result: dict[str, Any]) -> str:
    for key in ("prompt_ru", "prompt_en"):
        value = str(result.get(key) or "").strip()
        if value:
            return value

    raw = result.get("raw")
    if isinstance(raw, dict):
        for key in ("prompt_ru", "prompt", "output_text"):
            value = str(raw.get(key) or "").strip()
            if value:
                return value
    return ""


def install_vk_photo_prompt_result_compat() -> None:
    """Patch only ordinary photo-only result delivery in the legacy handler."""

    module = importlib.import_module("bot.handlers.image_analyzer")

    if getattr(module, "_vk_photo_prompt_result_compat_installed", False):
        return

    original_send = module._send_photo_prompt_result

    @wraps(original_send)
    async def send_photo_prompt_result(
        message: Any,
        result: dict[str, Any],
        *,
        filename: str = "photo_prompt_full.txt",
        document_caption: str = "📝 Полный prompt: RU + EN + negative",
    ) -> None:
        if str(result.get("source_mode") or "").strip() != "photo":
            await original_send(
                message,
                result,
                filename=filename,
                document_caption=document_caption,
            )
            return

        prompt = _prompt_from_result(result)
        if not prompt:
            await original_send(
                message,
                result,
                filename=filename,
                document_caption=document_caption,
            )
            return

        text, _was_trimmed = format_vk_photo_prompt_result(prompt)
        await message.answer(
            text,
            disable_web_page_preview=True,
            reply_markup=module.get_main_menu_button_keyboard(),
        )

    module._send_photo_prompt_result = send_photo_prompt_result
    module._vk_photo_prompt_result_compat_installed = True
