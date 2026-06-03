import asyncio
import base64
import html
import io
import json
import logging
import os
import random
import re
import time
import uuid
from datetime import datetime
from typing import Optional

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.database import (
    add_credits,
    add_credits_once,
    add_generation_history,
    add_generation_task,
    check_can_afford,
    complete_video_task,
    consume_free_generation,
    deduct_credits,
    refund_free_generation,
    get_or_create_user,
    get_task_by_id,
    get_user_credits,
    get_user_settings,
)
from bot.image_models import (
    IMAGE_OPTION_LABELS,
    get_image_model_config,
    get_image_option_label,
    normalize_image_options,
    resolve_image_model,
)
from bot.keyboards import (
    get_back_keyboard,
    get_create_image_keyboard,
    get_create_video_keyboard,
    get_animate_photo_keyboard,
    get_face_preservation_keyboard,
    get_gemini_omni_keyboard,
    get_image_result_keyboard,
    get_main_menu_keyboard,
    get_prompt_safety_keyboard,
    get_reference_images_upload_keyboard,
    get_reference_videos_upload_keyboard,
)
from bot.services.aleph_service import aleph_service
from bot.services.gemini_service import gemini_service
from bot.services.generation_guard import generation_lock_guard
from bot.services.storage_policy import choose_upload_category, public_upload_url, upload_path
from bot.services.gpt_image_service import gpt_image_service
from bot.services.grok_service import grok_service
from bot.services.gemini_omni_service import (
    GEMINI_OMNI_BASE_VOICES,
    GEMINI_OMNI_MAX_AUDIO_IDS,
    GEMINI_OMNI_MAX_CHARACTER_IDS,
    GEMINI_OMNI_MAX_IMAGES,
    GEMINI_OMNI_MAX_INPUT_UNITS,
    gemini_omni_service,
)
from bot.services.hailuo_service import hailuo_service
from bot.services.happyhorse_service import happyhorse_service
from bot.services.ideogram_service import ideogram_service
from bot.services.nano_banana_2_service import nano_banana_2_service
from bot.services.nano_banana_pro_service import nano_banana_pro_service
from bot.services.preset_manager import preset_manager
from bot.services.seedream_service import seedream_lite_service as seedream_service
from bot.services.subscription_service import subscription_service
from bot.services.veo_service import veo_service
from bot.states import GenerationStates
from bot.utils.help_texts import (
    UserHints,
    format_generation_options,
    get_aspect_ratio_help,
    get_editing_help,
    get_error_handling,
    get_model_selection_help,
    get_multiturn_help,
    get_prompt_tips,
    get_reference_images_help,
    get_resolution_help,
    get_search_grounding_help,
    get_success_message,
)
from bot.video_models import (
    VIDEO_OPTION_LABELS,
    get_video_model_config,
    get_video_option_label,
    normalize_video_options,
)

logger = logging.getLogger(__name__)
router = Router()

MIX_PHOTO_MODELS = ("banana_2", "grok_i2i", "gpt_image_2")

ANIMATE_PHOTO_PROMPTS = {
    "smile": "The person gently smiles, subtle natural facial motion, soft cinematic camera movement, realistic motion, keep identity and photo style.",
    "blink": "The person naturally blinks once or twice, tiny head movement, realistic facial animation, keep identity and original photo style.",
    "zoom": "Slow smooth camera push-in toward the subject, cinematic depth, natural parallax, keep the subject still and recognizable.",
    "wind": "A light breeze moves the hair and clothes naturally, subtle cinematic camera movement, realistic motion, keep identity and original photo style.",
    "walk": "The subject starts walking forward naturally toward the camera, smooth body movement, realistic animation, keep identity and outfit.",
    "talk": "The person starts speaking naturally with subtle lips and facial movement, gentle head motion, realistic portrait animation.",
    "dance": "The subject makes a short stylish dance move, smooth body motion, upbeat cinematic energy, keep identity and original styling.",
}


def _get_default_animate_model(preferred_model: str | None) -> str:
    if preferred_model in _MODELS_IMGTXT:
        return preferred_model
    return "v3_std"


def _get_image_state(data: dict) -> tuple[str, dict, list]:
    current_service = resolve_image_model(data.get("img_service", "banana_pro"))
    reference_images = data.get("reference_images", [])
    current_options = normalize_image_options(
        current_service,
        {
            "aspect_ratio": data.get("img_ratio"),
            **data.get("img_options", {}),
        },
    )
    return current_service, current_options, reference_images


async def _sync_image_state(
    state: FSMContext,
    model_id: str | None = None,
    option_updates: dict | None = None,
) -> tuple[str, dict, list]:
    data = await state.get_data()
    current_service, current_options, reference_images = _get_image_state(data)

    if model_id:
        current_service = resolve_image_model(model_id)
        current_options = normalize_image_options(current_service, current_options)

    if option_updates:
        current_options = normalize_image_options(
            current_service, {**current_options, **option_updates}
        )

    await state.update_data(
        img_service=current_service,
        img_ratio=current_options["aspect_ratio"],
        img_options=current_options,
    )
    return current_service, current_options, reference_images


def _format_image_settings(model_id: str, options: dict) -> str:
    model_config = get_image_model_config(model_id)
    lines = []
    for option_name in model_config["options"]:
        label = IMAGE_OPTION_LABELS.get(option_name, option_name)
        value = get_image_option_label(option_name, options[option_name])
        lines.append(f"• {label}: <code>{value}</code>")
    return "\n".join(lines)


def _build_image_creation_text(
    model_id: str,
    options: dict,
    reference_images: list,
    img_count: int = 1,
) -> str:
    ref_text = (
        f"📎 Референсов: <code>{len(reference_images)}</code>\n"
        if reference_images
        else ""
    )
    model_config = get_image_model_config(model_id)
    unit_cost = preset_manager.get_generation_cost(model_config["cost_key"])
    total_cost = unit_cost * max(1, int(img_count or 1))
    cost_text = (
        f"💰 Стоимость: <code>{total_cost}</code>🪙 "
        f"(<code>{img_count}</code>×<code>{unit_cost}</code>🪙)\n"
        if img_count and img_count > 1
        else f"💰 Стоимость: <code>{unit_cost}</code>🪙\n"
    )
    return (
        "🖼 <b>Создание фото</b>\n"
        f"{ref_text}"
        f"🤖 Модель: <code>{model_config['label']}</code>\n"
        f"{cost_text}"
        "⚙️ <b>Параметры:</b>\n"
        f"{_format_image_settings(model_id, options)}\n"
        "\n<b>Введите промпт для генерации:</b>\n"
        "Опишите сцену, стиль и детали результата."
    )


def _build_feed_retry_model_text(
    model_id: str,
    options: dict,
    reference_images: list,
    prompt: str,
    img_count: int = 1,
) -> str:
    model_config = get_image_model_config(model_id)
    unit_cost = preset_manager.get_generation_cost(model_config["cost_key"])
    total_cost = unit_cost * max(1, int(img_count or 1))
    prompt_preview = html.escape((prompt or "").strip())
    if len(prompt_preview) > 900:
        prompt_preview = prompt_preview[:900].rstrip() + "..."
    return (
        "🔁 <b>Повтор по промпту из ленты</b>\n\n"
        f"📎 Ваших референсов: <code>{len(reference_images)}</code>\n"
        f"🤖 Модель: <code>{model_config['label']}</code>\n"
        f"💰 Стоимость: <code>{total_cost}</code>🪙"
        f"{f' (<code>{img_count}</code>×<code>{unit_cost}</code>🪙)' if img_count > 1 else ''}\n\n"
        "📝 <b>Промпт (превью):</b>\n"
        f"<code>{prompt_preview}</code>\n\n"
        "⚙️ <b>Параметры:</b>\n"
        f"{_format_image_settings(model_id, options)}\n\n"
        "Можно изменить промпт перед запуском."
    )


async def _edit_feed_retry_control_message(
    target,
    text: str,
    reply_markup=None,
) -> int | None:
    message = target.message if isinstance(target, types.CallbackQuery) else target
    try:
        if getattr(message, "photo", None):
            await message.edit_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        else:
            await message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
        return message.message_id
    except Exception:
        if isinstance(target, types.CallbackQuery):
            try:
                await target.message.delete()
            except Exception:
                pass
            sent = await target.message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
            return sent.message_id
        else:
            sent = await target.answer(text, reply_markup=reply_markup, parse_mode="HTML")
            return sent.message_id


async def _edit_feed_retry_control_by_id(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup=None,
) -> int:
    try:
        await bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        return message_id
    except Exception:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
            return message_id
        except Exception:
            sent = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
            return sent.message_id


def _build_feed_retry_upload_text(prompt: str, current_count: int, max_refs: int = 14) -> str:
    prompt_preview = html.escape((prompt or "").strip())
    if len(prompt_preview) > 700:
        prompt_preview = prompt_preview[:700].rstrip() + "..."
    return (
        "🔁 <b>Повторить генерацию</b>\n\n"
        "Промпт исходной работы будет применён к вашим референсам.\n\n"
        "📝 <b>Промпт (превью):</b>\n"
        f"<code>{prompt_preview}</code>\n\n"
        "Полный текст доступен по кнопке ниже.\n"
        f"Загружено ваших фото: <code>{current_count}/{max_refs}</code>\n"
        "Отправьте ещё фото или переходите к выбору модели."
    )


def _build_feed_retry_full_prompt_text(prompt: str) -> str:
    escaped_prompt = html.escape((prompt or "").strip())
    max_prompt_len = 3400
    note = ""
    if len(escaped_prompt) > max_prompt_len:
        escaped_prompt = escaped_prompt[:max_prompt_len].rstrip() + "..."
        note = "\n\n<i>Промпт длиннее лимита одного сообщения. Для запуска сохранён полный текст.</i>"
    return (
        "📄 <b>Полный промпт из ленты</b>\n\n"
        f"<code>{escaped_prompt}</code>"
        f"{note}\n\n"
        "Можно заменить текст перед запуском."
    )


def _get_feed_retry_prompt_actions_keyboard():
    builder = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="✏️ Изменить промпт", callback_data="feed_retry_edit_prompt"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔙 Назад к повтору", callback_data="feed_retry_back_to_setup"
                )
            ],
        ]
    )
    return builder


def _build_mix_photo_prompt_text(ref_count: int) -> str:
    ref_line = (
        f"Загружено фото: <code>{ref_count}</code>\n\n" if ref_count else ""
    )
    return (
        "🧬 <b>Микс фото</b>\n\n"
        f"{ref_line}"
        "Один промпт уйдёт сразу в 3 нейросети: Banana 2, Grok и GPT Image 2.\n"
        "Перед запуском бот аккуратно улучшит промпт, чтобы снизить шанс ошибок.\n\n"
        "Напишите, какой результат нужен.\n"
        "Например: «сделай кинематографичный постер, реализм, мягкий свет»."
    )


def _build_image_waiting_text(*, mix_mode: bool, count: int) -> str:
    if mix_mode:
        return (
            "🧬 <b>Микс запущен</b>\n\n"
            "Отправляю запрос сразу в 3 нейросети.\n"
            "Сейчас каждая готовит свой вариант, результаты придут сюда по мере готовности.\n\n"
            "<i>Обычно это занимает 1-3 минуты.</i>"
        )
    if count > 1:
        return (
            "🖼 <b>Генерация запущена</b>\n\n"
            f"Запускаю <code>{count}</code> вариантов параллельно.\n"
            "Я на месте: как только модель отдаст результат, сразу пришлю его сюда.\n\n"
            "<i>Обычно это занимает 1-3 минуты.</i>"
        )
    return (
        "🖼 <b>Генерация запущена</b>\n\n"
        "Модель уже получила задачу и собирает картинку.\n"
        "Как только будет готово, пришлю результат сюда.\n\n"
        "<i>Обычно это занимает 1-3 минуты.</i>"
    )


def _clean_improved_prompt(raw_prompt: str) -> str:
    prompt = (raw_prompt or "").strip()
    if not prompt:
        return ""
    prompt = re.sub(r"^```(?:\w+)?\s*", "", prompt)
    prompt = re.sub(r"\s*```$", "", prompt).strip()
    return prompt.strip("\"' \n\t")


async def _improve_image_prompt(
    prompt: str,
    *,
    ref_count: int = 0,
    mix_mode: bool = False,
) -> str:
    """Improve weak image prompts without blocking generation on failures."""
    if len(prompt.strip()) < 3:
        return prompt

    mode_text = (
        "для функции AI image-to-image 'микс фото'"
        if mix_mode
        else "для AI-генерации изображения"
    )
    refs_text = (
        "Учитывай, что будет передано "
        f"{ref_count} фото-референсов: нужно явно попросить использовать их как "
        "основу для объекта, лица, стиля, композиции или деталей, если это следует "
        "из запроса. "
        if ref_count
        else ""
    )
    quality_text = (
        "качество, сохранение идентичности/важных деталей референсов."
        if ref_count
        else "качество, аккуратная композиция и понятный визуальный результат."
    )
    task = (
        f"Сделай пользовательский запрос безопаснее и понятнее {mode_text}. "
        "Нужно вернуть только финальный промпт, без вступления, markdown, кавычек и "
        "негативного промпта. Сохрани исходный смысл пользователя, не добавляй новые "
        "важные объекты без причины. Убери рискованные, двусмысленные или спорные "
        "формулировки, замени их нейтральными словами так, чтобы нейросеть с меньшей "
        f"вероятностью отклонила запрос. {refs_text}"
        "Если это не искажает замысел, сделай промпт конкретнее: сцена, действие, стиль, свет, камера, "
        f"{quality_text} "
        f"\n\nЗапрос пользователя: {prompt}"
    )
    try:
        from bot.services.gpt55_service import gpt55_service

        improved = await asyncio.wait_for(
            gpt55_service.ask(
                user_content=[{"type": "input_text", "text": task}],
                history=[],
                reasoning_effort="medium",
                web_search=False,
            ),
            timeout=45,
        )
    except Exception:
        logger.exception("Image prompt improvement failed")
        return prompt

    improved = _clean_improved_prompt(improved or "")
    if len(improved) < 3 or len(improved) > 6000:
        return prompt
    return improved


def _apply_face_preservation_prompt(prompt: str, face_mode: str, ref_count: int) -> str:
    """Add lightweight identity instructions selected by the user."""
    if not ref_count or face_mode == "none":
        return prompt

    if face_mode == "enhance":
        instruction = (
            "Use the reference photo(s) as identity guidance. Keep the person recognizable: "
            "preserve facial structure, age, eye color, face shape and distinctive features, "
            "but allow subtle flattering improvements to lighting, skin texture and photo quality."
        )
    else:
        instruction = (
            "Use the reference photo(s) as strict identity guidance. Preserve the exact person: "
            "facial structure, age, eye color, face shape, proportions, hairline and distinctive "
            "features must remain unchanged. Change only the requested style, background, outfit "
            "or scene."
        )
    return f"{prompt}\n\n{instruction}"


def _build_face_preservation_text(ref_count: int) -> str:
    return (
        "🔒 <b>Сохранить лицо</b>\n\n"
        "Бот не «обучает» нейросеть заново и не создаёт отдельную модель лица. "
        "Он передаёт загруженные референсы в генерацию и добавляет к запросу "
        "специальные инструкции, насколько строго сохранять внешность.\n\n"
        "Это помогает удержать:\n"
        "• черты лица\n"
        "• возраст\n"
        "• цвет глаз\n"
        "• форму лица\n"
        "• узнаваемость\n\n"
        f"Референсов загружено: <code>{ref_count}</code>\n\n"
        "<b>Выберите режим:</b>"
    )


def _build_prompt_safety_text(prompt: str) -> str:
    preview = html.escape(prompt[:700])
    if len(prompt) > 700:
        preview += "..."
    return (
        "🛡 <b>Сделать безопасный промпт?</b>\n\n"
        "Если выбрать «Сделать безопасным», бот перепишет запрос так, чтобы снизить "
        "риск отказа нейросети: уберёт рискованные формулировки, заменит спорные слова, "
        "сохранит смысл и сделает запрос более нейтральным.\n\n"
        "Если выбрать «Оставить как есть», генерация пойдёт с вашим текстом без изменений.\n\n"
        "<b>Ваш промпт:</b>\n"
        f"<code>{preview}</code>"
    )


async def _send_long_text(
    message: types.Message,
    header: str,
    text: str,
    *,
    chunk_size: int = 3200,
) -> None:
    chunks = [
        text[i : i + chunk_size]
        for i in range(0, len(text), chunk_size)
    ] or [""]
    for index, chunk in enumerate(chunks, start=1):
        title = header
        if len(chunks) > 1:
            title = f"{header} ({index}/{len(chunks)})"
        await message.answer(
            f"{title}\n\n<code>{html.escape(chunk)}</code>",
            parse_mode="HTML",
        )


async def _charge_generation_or_free_token(
    telegram_id: int,
    amount: int,
    *,
    reason: str,
    external_id: str,
    usage_type: str,
    model: str,
    metadata: dict | None = None,
) -> tuple[bool, str, int | None]:
    """Use subscription first, then free-generation token, then BoomCoin balance."""
    decision = await subscription_service.consume(
        telegram_id,
        usage_type=usage_type,
        model=model,
        external_id=external_id,
        metadata=metadata,
    )
    if decision.allowed:
        logger.info(
            "Consumed subscription usage for user %s: %s",
            telegram_id,
            decision.label,
        )
        return True, "subscription", decision.usage_id

    if await consume_free_generation(telegram_id):
        logger.info("Consumed free generation token for user %s", telegram_id)
        return True, "free_generation", None
    charged = await deduct_credits(
        telegram_id,
        amount,
        reason=reason,
        external_id=external_id,
        metadata=metadata,
    )
    return charged, "credits" if charged else "none", None


async def _refund_generation_charge(
    telegram_id: int,
    amount: int,
    *,
    billing_source: str,
    subscription_usage_id: int | None = None,
    reason: str,
    external_id: str,
    metadata: dict | None = None,
) -> None:
    if billing_source == "subscription":
        await subscription_service.refund(subscription_usage_id)
        return
    if billing_source == "free_generation":
        await refund_free_generation(telegram_id)
        return
    if billing_source == "credits" and not config.is_admin(telegram_id):
        await add_credits_once(
            telegram_id,
            amount,
            reason=reason,
            external_id=external_id,
            metadata=metadata,
        )


def _format_billing_status(amount: int, billing_source: str) -> str:
    if billing_source == "subscription":
        return "по подписке"
    if billing_source == "free_generation":
        return "бесплатная генерация"
    return f"<code>{amount}</code> BoomCoin списано"


def _build_image_task_started_text(
    *,
    prefix: str,
    model_label: str,
    task_id: str,
) -> str:
    return (
        f"🚀 {prefix}<b>{model_label}</b> приняла задачу\n\n"
        f"Код: <code>{html.escape(str(task_id))}</code>\n"
        "Работа идёт, результат придёт сюда автоматически.\n\n"
        "<i>Можно закрыть чат и вернуться позже.</i>"
    )


def _build_video_waiting_text(
    *,
    model: str,
    duration: int,
    ratio: str,
    cost: int,
) -> str:
    return (
        "🎬 <b>Видео запущено в работу</b>\n\n"
        f"🤖 Модель: <code>{html.escape(str(model))}</code>\n"
        f"⏱ Длительность: <code>{duration}s</code>\n"
        f"📐 Формат: <code>{html.escape(str(ratio))}</code>\n"
        f"💰 Стоимость: <code>{cost}</code>🪙\n\n"
        "Сейчас модель собирает кадры и движение. "
        "Результат придёт сюда автоматически.\n\n"
        "<i>Обычно это занимает 1-5 минут.</i>"
    )


def _build_video_task_started_text(
    *,
    task_id: str,
    model: str,
    duration: int,
    ratio: str,
    cost: int,
    is_admin: bool,
) -> str:
    price_text = "(админ бесплатно)" if is_admin else "списано"
    ratio_text = (
        "формат по стартовому фото" if model == "wan_27_i2v" else str(ratio)
    )
    return (
        "✅ <b>Видео задача принята</b>\n\n"
        f"Код: <code>{html.escape(str(task_id))}</code>\n"
        f"🎯 <code>{html.escape(str(model))}</code> | {duration}s | {html.escape(ratio_text)}\n"
        f"💰 <code>{cost}</code>🪙 {price_text}\n\n"
        "Работа идёт, результат появится в этом чате автоматически."
    )


def _progress_bar(percent: int) -> str:
    percent = max(0, min(100, percent))
    filled = max(1, round(percent / 10)) if percent else 0
    return "🟩" * filled + "⬜" * (10 - filled)


def _build_progress_text(
    *,
    title: str,
    percent: int,
    status: str,
    task_id: str | None = None,
    eta: str | None = None,
) -> str:
    code_line = f"\nКод: <code>{html.escape(str(task_id))}</code>" if task_id else ""
    eta_line = f"\n\n<i>{html.escape(eta)}</i>" if eta else ""
    return (
        f"{title}\n\n"
        f"{_progress_bar(percent)} <code>{percent}%</code>\n"
        f"{html.escape(status)}"
        f"{code_line}"
        f"{eta_line}"
    )


async def _simulate_generation_progress(
    message: types.Message,
    task_id: str,
    *,
    title: str,
    eta: str,
    steps: tuple[tuple[int, str], ...],
    interval: int = 12,
) -> None:
    for percent, status in steps:
        await asyncio.sleep(interval)
        try:
            task = await get_task_by_id(task_id)
            if task and task.status == "completed":
                final_status = (
                    "Готово. Отправляю результат в чат."
                    if task.result_url
                    else "Задача завершилась. Отправляю статус в чат."
                )
                await message.edit_text(
                    _build_progress_text(
                        title=title,
                        percent=100,
                        status=final_status,
                        task_id=task_id,
                    ),
                    parse_mode="HTML",
                )
                return

            await message.edit_text(
                _build_progress_text(
                    title=title,
                    percent=percent,
                    status=status,
                    task_id=task_id,
                    eta=eta,
                ),
                parse_mode="HTML",
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                continue
            return
        except Exception:
            logger.debug("Progress update failed for task %s", task_id, exc_info=True)
            return


_MODELS_TEXT = {
    "gemini_omni",
    "v3_std",
    "v3_pro",
    "runway",
    "veo3_fast",
    "veo3",
    "veo3_lite",
    "hailuo_pro",
    "hailuo_std",
    "happyhorse_t2v",
    "wan_27_t2v",
}
_MODELS_IMGTXT = {
    "gemini_omni",
    "v3_std",
    "v3_pro",
    "seedance2",
    "runway",
    "grok_imagine",
    "veo3_fast",  # only veo3_fast supports image reference; veo3/veo3_lite are text-only
    "hailuo_23_pro",
    "hailuo_23_std",
    "hailuo_i2v_pro",
    "hailuo_i2v_std",
    "happyhorse_i2v",
    "happyhorse_ref2v",
    "wan_27_i2v",
}
_MODELS_VIDEO = {
    "gemini_omni",
    "aleph",
    "glow",
    "happyhorse_edit",
}


def _clamp_model_for_type(model: str, v_type: str) -> str:
    if v_type == "text" and model not in _MODELS_TEXT:
        return "v3_std"
    if v_type == "imgtxt" and model not in _MODELS_IMGTXT:
        return "v3_std"
    if v_type == "video" and model not in _MODELS_VIDEO:
        return "aleph"
    return model


def _get_video_ui_state(data: dict) -> dict:
    model = data.get("v_model", "v3_std")
    return {
        "current_v_type": data.get("v_type", "text"),
        "current_model": model,
        "current_duration": data.get("v_duration", 5),
        "current_ratio": data.get("v_ratio", "16:9"),
        "current_mode": data.get("v_mode", "720p"),
        "current_orientation": data.get("v_orientation", "video"),
        "current_grok_mode": data.get("grok_mode", "normal"),
        "current_hailuo_resolution": data.get("hailuo_resolution", "768P"),
        "current_video_options": normalize_video_options(
            model, data.get("video_options", {})
        ),
    }


def _format_video_settings(data: dict) -> str:
    ui = _get_video_ui_state(data)
    type_text = {
        "text": "Текст → Видео",
        "imgtxt": "Фото + Текст → Видео",
        "video": "Видео + Текст → Видео",
    }.get(ui["current_v_type"], ui["current_v_type"])

    model_title = get_video_model_config(ui["current_model"]).get("label", ui["current_model"])
    lines = [
        "⚙️ <b>Текущие настройки:</b>",
        f"• Тип: <code>{type_text}</code>",
        f"• Модель: <code>{model_title}</code>",
        f"• Длительность: <code>{ui['current_duration']} сек</code>",
    ]

    model_config = get_video_model_config(ui["current_model"])
    if model_config.get("aspect_ratios"):
        lines.append(f"• Формат: <code>{ui['current_ratio']}</code>")
    elif ui["current_model"] == "wan_27_i2v":
        lines.append("• Формат: <code>по стартовому фото</code>")

    for option_name in model_config.get("options", {}):
        value = ui["current_video_options"].get(option_name)
        label = VIDEO_OPTION_LABELS.get(option_name, option_name)
        lines.append(
            f"• {label}: <code>{get_video_option_label(option_name, value)}</code>"
        )
    if ui["current_model"] == "gemini_omni":
        seed = ui["current_video_options"].get("seed")
        lines.append(f"• Seed: <code>{seed if seed is not None else 'auto'}</code>")
        audio_count = len(data.get("omni_audio_ids", []))
        character_count = len(data.get("omni_character_ids", []))
        if audio_count or character_count:
            lines.append(
                f"• Omni ID: <code>{audio_count} audio / {character_count} character</code>"
            )

    return "\n".join(lines)


def _format_omni_context(data: dict) -> str:
    audio_ids = data.get("omni_audio_ids", [])
    character_ids = data.get("omni_character_ids", [])
    user_images_count = (1 if data.get("v_image_url") else 0) + len(
        data.get("reference_images", [])
    )
    effective_images = _get_gemini_omni_effective_image_urls(data)
    images_count = len(effective_images)
    videos_count = len(data.get("v_reference_videos", []))
    video_options = normalize_video_options("gemini_omni", data.get("video_options"))
    duration = data.get("v_duration", 4)
    ratio = data.get("v_ratio", "16:9")
    resolution = video_options.get("resolution", "720p")
    seed = video_options.get("seed")
    input_units = images_count + videos_count * 2 + len(character_ids)
    remaining_units = max(0, GEMINI_OMNI_MAX_INPUT_UNITS - input_units)
    source_images = data.get("omni_character_source_images", [])
    visual_hint = (
        "\n🖼 Фото персонажа будет добавлено в видео автоматически."
        if source_images or data.get("omni_character_image_url")
        else ""
    )
    return (
        "🔷 <b>Gemini Omni</b>\n\n"
        f"🎙 Голоса: <code>{len(audio_ids)}</code>/{GEMINI_OMNI_MAX_AUDIO_IDS}\n"
        f"🧍 Персонажи: <code>{len(character_ids)}</code>/{GEMINI_OMNI_MAX_CHARACTER_IDS}\n"
        f"🖼 Фото: <code>{images_count}</code>/{GEMINI_OMNI_MAX_IMAGES}"
        f" (ваших <code>{user_images_count}</code>)\n"
        f"📹 Видео: <code>{videos_count}</code>/1\n"
        f"⏱ Время: <code>{duration} сек"
        f"{' (не влияет при видео-рефе)' if videos_count else ''}</code>\n"
        f"💎 Качество: <code>{resolution}</code>\n"
        f"📐 Формат: <code>{ratio}</code>\n"
        f"🌱 Seed: <code>{seed if seed is not None else 'auto'}</code>\n"
        f"📦 Входы: <code>{input_units}/{GEMINI_OMNI_MAX_INPUT_UNITS}</code> "
        f"(свободно <code>{remaining_units}</code>)"
        f"{visual_hint}\n\n"
        "<b>Как пользоваться:</b>\n"
        "1. Лучший multimodal режим: <b>Фото + видео</b> — фото задаёт объект/сцену, видео задаёт движение.\n"
        "2. Быстрый запуск: нажмите <b>Запустить видео</b>, затем напишите промпт обычным сообщением.\n"
        "3. Фото-рефы: <b>Добавить фото</b> — стиль, сцена, объект или первый кадр.\n"
        "4. Видео-реф: <b>Добавить видео</b> — движение, камера или атмосфера.\n"
        "5. Голос: <b>Голос</b> — просто опишите голос, ID добавится автоматически.\n"
        "6. Персонаж: <b>Персонаж</b> — отправьте фото и описание, ID добавится автоматически.\n\n"
        "<b>Важно:</b> голос и персонаж не обязательны. Можно генерировать только по тексту "
        "или по фото + тексту. Если добавлено видео, настройка секунд не влияет."
    )


def _gemini_omni_keyboard_from_data(data: dict):
    video_options = normalize_video_options("gemini_omni", data.get("video_options"))
    return get_gemini_omni_keyboard(
        len(data.get("omni_audio_ids", [])),
        len(data.get("omni_character_ids", [])),
        duration=int(data.get("v_duration", 4)),
        resolution=video_options.get("resolution", "720p"),
        ratio=data.get("v_ratio", "16:9"),
    )


def _parse_key_value_lines(text: str) -> dict:
    result = {}
    positional = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            positional.append(line)
            continue
        result[key.strip().lower()] = value.strip()
    if positional:
        result["_positional"] = positional
    return result


def _unique_urls(urls: list[str]) -> list[str]:
    result = []
    for url in urls:
        if url and url not in result:
            result.append(url)
    return result


def _get_gemini_omni_effective_image_urls(data: dict) -> list[str]:
    images = []
    if data.get("v_image_url"):
        images.append(data["v_image_url"])
    images.extend(data.get("reference_images", []))
    character_images = data.get("omni_character_source_images", [])
    last_character_image = data.get("omni_character_image_url")
    if last_character_image:
        character_images = [last_character_image, *character_images]
    images.extend(character_images)
    return _unique_urls(images)


def _pick_gemini_omni_base_voice(description: str) -> str:
    """Select a reasonable Gemini Omni base voice from a free-form prompt."""
    lowered = description.lower()
    if any(
        marker in lowered
        for marker in (
            "писк",
            "мил",
            "нежн",
            "cute",
            "sweet",
            "high",
            "soft",
            "girl",
            "жен",
            "дет",
        )
    ):
        return "aoede"
    if any(
        marker in lowered
        for marker in ("низ", "глуб", "бас", "муж", "deep", "low", "male")
    ):
        return "charon"
    if any(marker in lowered for marker in ("энерг", "быстр", "puck", "playful")):
        return "puck"
    return "achernar"


def _make_gemini_omni_voice_name(description: str) -> str:
    cleaned = re.sub(r"\s+", " ", description).strip()
    if cleaned:
        return cleaned[:40]
    return f"Omni voice {int(time.time())}"


def _make_gemini_omni_character_name(description: str) -> str:
    cleaned = re.sub(r"\s+", " ", description).strip()
    if cleaned:
        return cleaned[:40]
    return f"Omni character {int(time.time())}"


def _looks_like_voice_description(text: str) -> bool:
    cleaned = text.strip()
    if len(cleaned) < 3:
        return False
    return bool(re.search(r"[A-Za-zА-Яа-яЁё]", cleaned))


# =============================================================================
# НОВЫЙ UX: МЕНЮ СОЗДАНИЯ ВИДЕО (get_create_video_keyboard)
# =============================================================================


@router.callback_query(F.data == "create_video_new")
async def show_create_video_menu(callback: types.CallbackQuery, state: FSMContext):
    """Показывает меню создания видео - начинаем с загрузки референсов"""
    from bot.database import get_user_credits

    user_credits = await get_user_credits(callback.from_user.id)

    # Инициализируем опции по умолчанию
    await state.update_data(
        generation_type="video",
        v_type="text",  # text или imgtxt
        v_model="v3_std",  # модель видео
        v_duration=5,
        v_ratio="16:9",
        reference_images=[],  # Реф. изображения для всех режимов (до 14)
        v_reference_videos=[],  # Реф. видео для video+text (до 5)
        user_prompt="",  # Инициализируем пустой промпт
    )

    # СРАЗУ показываем экран с параметрами видео и полем для промпта (без загрузки референсов)
    await _show_video_creation_screen(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "create_image_refs_new")
async def show_create_image_menu(callback: types.CallbackQuery, state: FSMContext):
    """Показывает меню создания фото - начинаем с загрузки референсов"""
    user_credits = await get_user_credits(callback.from_user.id)

    # Инициализируем опции по умолчанию
    default_options = normalize_image_options("banana_pro")
    await state.update_data(
        generation_type="image",
        img_service="banana_pro",
        img_ratio=default_options["aspect_ratio"],
        img_options=default_options,
        reference_images=[],  # Инициализируем пустой список референсов
        preset_id="new",  # Для нового UX - указываем, что это "new" режим
    )

    # Показываем экран загрузки референсов (ШАГ 1)
    text = (
        "🖼 <b>Создание фото</b>\n\n"
        f"🪙 Ваш баланс: <code>{user_credits}</code> BoomCoin\n\n"
        "<b>Шаг 1: загрузка референсов</b>\n"
        "Это необязательно, но полезно для:\n"
        "• сходства с объектом\n"
        "• сохранения стиля\n"
        "• консистентных персонажей\n\n"
        "Можно загрузить до 14 изображений.\n"
        "После этого нажмите «Продолжить» или «Пропустить»."
    )
    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_reference_images_upload_keyboard(0, 14, "new"),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            text,
            reply_markup=get_reference_images_upload_keyboard(0, 14, "new"),
            parse_mode="HTML",
        )
    await callback.answer()
    await state.set_state(GenerationStates.uploading_reference_images)


@router.callback_query(F.data == "quick_animate_photo")
async def quick_animate_photo(callback: types.CallbackQuery, state: FSMContext):
    """Shortcut: photo to video via Grok Imagine."""
    default_options = normalize_video_options("grok_imagine")
    await state.update_data(
        generation_type="video",
        v_type="imgtxt",
        v_model="grok_imagine",
        v_duration=6,
        v_ratio="16:9",
        video_options=default_options,
        grok_mode="normal",
        reference_images=[],
        v_reference_videos=[],
        user_prompt="",
        v_image_url=None,
    )
    await callback.message.edit_text(
        "📸 <b>Оживить фото</b>\n\n"
        "Отправьте фото, которое нужно превратить в короткое видео.\n"
        "После фото напишите движение: например, «улыбается и медленно смотрит в камеру».",
        reply_markup=get_create_video_keyboard(
            current_v_type="imgtxt",
            current_model="grok_imagine",
            current_duration=6,
            current_ratio="16:9",
            current_video_options=default_options,
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data.startswith("animate_img_"))
async def open_animate_generated_photo(callback: types.CallbackQuery, state: FSMContext):
    """Open a separate animate-photo menu for a generated image result."""
    task_id = callback.data.replace("animate_img_", "", 1)
    task = await get_task_by_id(task_id)
    if not task or not task.result_url:
        await callback.answer("Не нашёл готовое фото для оживления", show_alert=True)
        return
    if task.telegram_id != callback.from_user.id:
        await callback.answer("Это фото из другой сессии", show_alert=True)
        return

    settings = await get_user_settings(callback.from_user.id)
    v_model = _get_default_animate_model(settings.get("preferred_i2v_model"))
    video_options = normalize_video_options(v_model)
    model_config = get_video_model_config(v_model)
    durations = model_config.get("durations") or [5]
    ratios = model_config.get("aspect_ratios") or ["16:9"]

    await state.update_data(
        generation_type="video",
        v_type="imgtxt",
        v_model=v_model,
        v_duration=5 if 5 in durations else durations[0],
        v_ratio="16:9" if "16:9" in ratios else ratios[0],
        video_options=video_options,
        reference_images=[],
        v_reference_videos=[],
        user_prompt="",
        v_image_url=task.result_url,
        animate_source_task_id=task_id,
    )

    await callback.message.answer(
        "📸 <b>Оживить фото</b>\n\n"
        "Выберите движение из меню или нажмите «Свой вариант» и напишите, как оживить фото.\n"
        "Фото уже сохранено как стартовый кадр для видео.",
        reply_markup=get_animate_photo_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data.startswith("animate_preset_"))
async def handle_animate_photo_preset(callback: types.CallbackQuery, state: FSMContext):
    """Run image-to-video from the saved generated photo and selected motion preset."""
    preset = callback.data.replace("animate_preset_", "", 1)
    data = await state.get_data()
    if not data.get("v_image_url"):
        await callback.answer("Сначала выберите готовое фото", show_alert=True)
        return

    if preset == "custom":
        await callback.message.answer(
            "🎬 Напишите одним сообщением, как именно оживить фото.\n"
            "Например: <code>улыбается, камера медленно приближается, ветер в волосах</code>",
            parse_mode="HTML",
        )
        await callback.answer()
        await state.set_state(GenerationStates.waiting_for_video_prompt)
        return

    prompt = ANIMATE_PHOTO_PROMPTS.get(preset)
    if not prompt:
        await callback.answer("Неизвестный вариант", show_alert=True)
        return

    await callback.answer("Запускаю оживление...")
    await run_no_preset_video_from_message(callback, state, prompt)


@router.callback_query(F.data == "animate_settings")
async def open_animate_photo_settings(callback: types.CallbackQuery, state: FSMContext):
    """Open the full video settings screen while keeping the generated photo reference."""
    data = await state.get_data()
    if not data.get("v_image_url"):
        await callback.answer("Сначала выберите готовое фото", show_alert=True)
        return
    await _show_video_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "quick_mix_photo")
async def quick_mix_photo(callback: types.CallbackQuery, state: FSMContext):
    """Shortcut: upload references and mix them into a new image."""
    data = await state.get_data()
    existing_refs = data.get("reference_images", [])
    options = normalize_image_options("banana_2")
    await state.update_data(
        generation_type="image",
        img_service="banana_2",
        img_ratio=options["aspect_ratio"],
        img_options=options,
        img_count=1,
        reference_images=existing_refs,
        mix_mode=True,
        preset_id="new",
    )

    if existing_refs:
        await callback.message.edit_text(
            _build_mix_photo_prompt_text(len(existing_refs)),
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
        await callback.answer()
        await state.set_state(GenerationStates.waiting_for_input)
        return

    await callback.message.edit_text(
        "🧬 <b>Микс фото</b>\n\n"
        "Загрузите хотя бы 1 фото-референс и нажмите «Продолжить».\n"
        "После промпта бот улучшит запрос и отправит его в 3 нейросети: Banana 2, Grok и GPT Image 2.",
        reply_markup=get_reference_images_upload_keyboard(0, 14, "new"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.uploading_reference_images)


@router.callback_query(F.data == "motion_control")
async def start_motion_control(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    """Запуск Motion Control Kling 2.6"""
    from bot.database import get_user_credits
    from bot.services.preset_manager import preset_manager

    user_credits = await get_user_credits(callback.from_user.id)
    video_model = "v26_motion_pro"
    price_per_second = preset_manager.get_video_cost(video_model, 1)

    await state.update_data(
        generation_type="motion_control",
        video_model=video_model,
        mode="pro",
        price_per_second=price_per_second,
        motion_mode="720p",
        motion_orientation="video",
        motion_image_url=None,
        motion_video_url=None,
        motion_prompt="",
    )

    text = (
        "🎯 <b>Kling 2.6 Motion Control</b>\n\n"
        f"🪙 Баланс: <code>{user_credits}</code>\n\n"
        f"Цена: <code>{price_per_second}</code>🪙/сек "
        "по длительности видео движения.\n\n"
        "<b>Шаг 1: Reference Image</b>\n"
        "Загрузите чёткое фото субъекта:\n"
        "• голова, плечи, торс\n"
        "• формат JPEG или PNG\n"
        "• размер до 10 MB\n\n"
        "<i>Это фото станет персонажем, который повторит движение из видео.</i>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard("back_main"),
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_motion_character_image)


@router.callback_query(F.data == "photo_prompt")
async def show_photo_prompt(callback: types.CallbackQuery, state: FSMContext):
    """Простой промпт для фото (без референсов и выбора параметров)"""
    user_credits = await get_user_credits(callback.from_user.id)
    default_options = normalize_image_options("banana_pro")

    await state.update_data(
        generation_type="image",
        img_service="banana_pro",
        img_ratio=default_options["aspect_ratio"],
        img_options=default_options,
    )

    await callback.message.edit_text(
        _build_image_creation_text("banana_pro", default_options, [], 1),
        reply_markup=get_create_image_keyboard(
            current_service="banana_pro",
            current_ratio=default_options["aspect_ratio"],
            num_refs=0,
            current_options=default_options,
        ),
        parse_mode="HTML",
    )

    await callback.answer()
    await state.set_state(GenerationStates.confirming_reference_images)


@router.callback_query(F.data == "img_ref_upload_new")
async def handle_img_ref_upload_new(callback: types.CallbackQuery, state: FSMContext):
    """Показывает меню загрузки референсных изображений для нового UX"""
    data = await state.get_data()
    # Показываем клавиатуру загрузки референсов
    await callback.message.edit_text(
        "📎 <b>Загрузка референсов</b>\n\n"
        "Загрузите до 14 изображений.\n"
        "После загрузки нажмите «Продолжить» или «Пропустить».",
        reply_markup=get_reference_images_upload_keyboard(0, 14, "new"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.uploading_reference_images)


# =============================================================================
# СЛУЖЕБНЫЕ ФУНКЦИИ ДЛЯ UNIFIED UX
# =============================================================================


async def _show_video_creation_screen(
    message_or_callback, state: FSMContext, edit: bool = True
):
    """
    Показывает единый экран создания видео с параметрами и промптом.
    Используется после загрузки референсов или при пропуске.
    """
    data = await state.get_data()

    # Получаем текущие параметры
    ui = _get_video_ui_state(data)
    current_v_type = ui["current_v_type"]
    current_model = ui["current_model"]
    current_duration = ui["current_duration"]
    current_ratio = ui["current_ratio"]
    reference_images = data.get("reference_images", [])
    v_reference_videos = data.get("v_reference_videos", [])
    v_image_url = data.get("v_image_url")
    user_prompt = data.get("user_prompt", "")

    # Формируем текст о референсах
    ref_text = ""
    if reference_images:
        ref_text = f"📎 Изображений реф: <code>{len(reference_images)}</code>\n"
    if v_reference_videos:
        ref_text += f"📹 Видео реф: <code>{len(v_reference_videos)}</code>\n"

    # Формируем статус медиа в зависимости от типа
    media_status = ""
    if current_v_type == "imgtxt":
        start_count = 1 if v_image_url else 0
        ref_count = len(reference_images)
        total = start_count + ref_count
        max_photos = GEMINI_OMNI_MAX_IMAGES if current_model == "gemini_omni" else 9
        if total > 0:
            media_status = f"✅ <b>Фото загружено: {total}/{max_photos}</b> (старт + рефы)\n"
        else:
            media_status = "📷 <b>Загрузите стартовое изображение</b>\n"
        if current_model == "gemini_omni":
            media_status += (
                "🔷 Gemini Omni может работать с текстом, фото и 1 видео-референсом; "
                "голос и персонаж можно не добавлять.\n"
            )
    elif current_v_type == "video":
        if v_reference_videos:
            media_status = f"✅ <b>{len(v_reference_videos)} реф. видео загружено!</b>\n"
        else:
            media_status = "📹 <b>Загрузите референсные видео (до 5)</b>\n"

    prompt_text = ""
    if user_prompt:
        prompt_text = (
            "\n📝 <b>Промпт:</b>\n"
            f"<code>{user_prompt[:100]}{'...' if len(user_prompt) > 100 else ''}</code>\n"
        )

    title = "🎬 <b>Создание видео</b>"
    prompt_hint = (
        "\n<b>Введите промпт для генерации:</b>\n"
        "• что происходит в сцене\n"
        "• как движется камера\n"
        "• какой нужен стиль и настрой"
    )
    if current_model == "grok_imagine":
        title = "🧠 <b>Grok Imagine 1.5</b>"
        prompt_hint = (
            "\n<b>Что дальше:</b>\n"
            "1. Выберите формат, длительность и режим ниже\n"
            "2. При необходимости загрузите/замените стартовое фото\n"
            "3. Отправьте промпт с описанием движения"
        )

    text = (
        f"{title}\n\n"
        f"{ref_text}"
        f"{_format_video_settings(data)}\n"
        f"{media_status}"
        f"{prompt_text}"
        f"{prompt_hint}"
    )

    # Напоминание о загрузке медиа
    if current_v_type == "imgtxt" and not v_image_url:
        text += "\n\n<i>📷 Загрузите фото, которое станет первым кадром видео.</i>"
    elif current_v_type == "video" and not v_reference_videos:
        text += "\n\n<i>📹 Загрузите референсные видео: до 5 файлов, длительность 3-10 сек.</i>"
    elif current_v_type == "video" and current_model == "happyhorse_edit":
        text += "\n\n<i>🖼 Для HappyHorse Edit можно добавить фото-референсы через режим «Фото + Текст», затем вернуться к редактированию видео.</i>"

    keyboard = get_create_video_keyboard(
        current_v_type=current_v_type,
        current_model=current_model,
        current_duration=current_duration,
        current_ratio=current_ratio,
        current_mode=ui["current_mode"],
        current_orientation=ui["current_orientation"],
        current_grok_mode=ui["current_grok_mode"],
        current_hailuo_resolution=ui["current_hailuo_resolution"],
        current_video_options=ui["current_video_options"],
    )
    # Используем edit для callback, send для message
    try:
        await message_or_callback.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        target = (
            message_or_callback.message
            if hasattr(message_or_callback, "message")
            else message_or_callback
        )
        await target.answer(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        target = (
            message_or_callback.message
            if hasattr(message_or_callback, "message")
            else message_or_callback
        )
        await target.answer(text, reply_markup=keyboard, parse_mode="HTML")

    # Устанавливаем состояние ожидания промпта для видео
    await state.set_state(GenerationStates.waiting_for_video_prompt)
    logger.info(
        f"[DEBUG] State set to waiting_for_video_prompt for user {message_or_callback.from_user.id if hasattr(message_or_callback, 'from_user') else 'callback'}"
    )


@router.callback_query(F.data == "img_ref_skip_new")
async def handle_img_ref_skip_new(callback: types.CallbackQuery, state: FSMContext):
    """Пропускает загрузку референсов и переходит к вводу промпта"""
    data = await state.get_data()
    generation_type = data.get("generation_type")

    if data.get("mix_mode"):
        await callback.answer(
            "Для микса загрузите хотя бы 1 фото-референс.",
            show_alert=True,
        )
        return

    # Очищаем референсы
    await state.update_data(reference_images=[], face_preservation_mode="none")

    if generation_type == "video":
        # Для видео - показываем параметры видео и промпт
        await _show_video_creation_screen(callback.message, state)
        await callback.answer()
    else:
        # Для фото - показываем параметры фото
        current_service, current_options, _ = await _sync_image_state(state)

        await callback.message.edit_text(
            _build_image_creation_text(
                current_service,
                current_options,
                [],
                data.get("img_count", 1),
            ),
            reply_markup=get_create_image_keyboard(
                current_service=current_service,
                current_ratio=current_options["aspect_ratio"],
                num_refs=0,
                current_options=current_options,
            ),
            parse_mode="HTML",
        )

        await callback.answer()
        await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "img_ref_continue_new")
async def handle_img_ref_continue_new(callback: types.CallbackQuery, state: FSMContext):
    """Продолжает после загрузки референсов - сразу к параметрам видео (без проверки наличия референсов)"""
    # УБРАНА ПРОВЕРКА: референсы опциональны, всегда продолжаем
    data = await state.get_data()
    generation_type = data.get("generation_type")

    if data.get("mix_mode"):
        current_refs = data.get("reference_images", [])
        if not current_refs:
            await callback.answer(
                "Для микса загрузите хотя бы 1 фото-референс.",
                show_alert=True,
            )
            return

        options = normalize_image_options(
            "banana_2",
            {"aspect_ratio": data.get("img_ratio"), **data.get("img_options", {})},
        )
        await state.update_data(
            generation_type="image",
            img_service="banana_2",
            img_ratio=options["aspect_ratio"],
            img_options=options,
            img_count=1,
        )
        await callback.message.edit_text(
            _build_mix_photo_prompt_text(len(current_refs)),
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
        await callback.answer()
        await state.set_state(GenerationStates.waiting_for_input)
        return

    if generation_type == "video":
        # Сразу показываем единый экран с параметрами и промптом (без подтверждения)
        await _show_video_creation_screen(callback.message, state)
        await callback.answer()
        return
    else:
        # Для фото - показываем параметры фото
        current_service, current_options, current_refs = await _sync_image_state(state)
        if current_refs:
            await callback.message.edit_text(
                _build_face_preservation_text(len(current_refs)),
                reply_markup=get_face_preservation_keyboard(),
                parse_mode="HTML",
            )
            await callback.answer()
            await state.set_state(GenerationStates.selecting_face_preservation)
            return

        await callback.message.edit_text(
            _build_image_creation_text(
                current_service,
                current_options,
                current_refs,
                data.get("img_count", 1),
            ),
            reply_markup=get_create_image_keyboard(
                current_service=current_service,
                current_ratio=current_options["aspect_ratio"],
                num_refs=len(current_refs),
                current_options=current_options,
            ),
            parse_mode="HTML",
        )

        await callback.answer()
        await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "ref_reload_new")
async def handle_ref_reload_new(callback: types.CallbackQuery, state: FSMContext):
    """Перезагружает референсы (очищает и начинает заново) для нового UX"""
    data = await state.get_data()
    generation_type = data.get("generation_type")

    # Очищаем референсы
    await state.update_data(reference_images=[])

    # Определяем preset_id для клавиатуры
    preset_id = "new" if generation_type != "video" else "video_new"

    await callback.message.edit_text(
        "📎 <b>Перезагрузка референсов</b>\n\n"
        "Загружено: <code>0/14</code>\n"
        "Отправьте новые изображения для загрузки.",
        reply_markup=get_reference_images_upload_keyboard(0, 14, preset_id),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.uploading_reference_images)


@router.callback_query(F.data == "ref_confirm_new")
async def handle_ref_confirm_new(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждает референсы для нового UX - переходит к выбору модели/формата"""
    data = await state.get_data()
    current_refs = data.get("reference_images", [])

    if not current_refs:
        await callback.answer("Нет загруженных изображений", show_alert=True)
        return

    current_service, current_options, current_refs = await _sync_image_state(state)

    await callback.message.edit_text(
        _build_image_creation_text(
            current_service,
            current_options,
            current_refs,
            data.get("img_count", 1),
        ),
        reply_markup=get_create_image_keyboard(
            current_service=current_service,
            current_ratio=current_options["aspect_ratio"],
            num_refs=len(current_refs),
            current_options=current_options,
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("face_mode_"))
async def handle_face_preservation_mode(
    callback: types.CallbackQuery, state: FSMContext
):
    """Сохраняет режим лица и переводит пользователя к выбору модели/формата."""
    mode = callback.data.replace("face_mode_", "", 1)
    if mode not in {"strict", "enhance", "none"}:
        await callback.answer("Неизвестный режим", show_alert=True)
        return

    await state.update_data(face_preservation_mode=mode)
    data = await state.get_data()
    current_service, current_options, current_refs = await _sync_image_state(state)
    await callback.message.edit_text(
        _build_image_creation_text(
            current_service,
            current_options,
            current_refs,
            data.get("img_count", 1),
        ),
        reply_markup=get_create_image_keyboard(
            current_service=current_service,
            current_ratio=current_options["aspect_ratio"],
            num_refs=len(current_refs),
            current_options=current_options,
            img_count=data.get("img_count", 1),
        ),
        parse_mode="HTML",
    )
    labels = {
        "strict": "максимально сохранить",
        "enhance": "немного улучшить",
        "none": "без дополнительных инструкций",
    }
    await callback.answer(f"Режим: {labels[mode]}")
    await state.set_state(GenerationStates.waiting_for_input)


# Обработчики для меню создания видео
@router.callback_query(F.data == "v_type_text")
async def handle_v_type_text(callback: types.CallbackQuery, state: FSMContext):
    """Выбор типа генерации: текст"""
    data = await state.get_data()
    ui = _get_video_ui_state(data)
    clamped_model = _clamp_model_for_type(ui["current_model"], "text")
    await state.update_data(v_type="text", v_model=clamped_model)

    await callback.message.edit_reply_markup(
        reply_markup=get_create_video_keyboard(
            current_v_type="text",
            current_model=clamped_model,
            current_duration=ui["current_duration"],
            current_ratio=ui["current_ratio"],
            current_mode=ui["current_mode"],
            current_orientation=ui["current_orientation"],
            current_grok_mode=ui["current_grok_mode"],
            current_hailuo_resolution=ui["current_hailuo_resolution"],
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "v_type_imgtxt")
async def handle_v_type_imgtxt(callback: types.CallbackQuery, state: FSMContext):
    """Выбор типа генерации: фото+текст - запрашиваем изображение на том же экране"""
    data = await state.get_data()
    ui = _get_video_ui_state(data)
    v_image_url = data.get("v_image_url")
    clamped_model = _clamp_model_for_type(ui["current_model"], "imgtxt")
    await state.update_data(v_type="imgtxt", v_model=clamped_model)

    # Показываем сообщение с просьбой загрузить изображение на ТОМ ЖЕ экране
    image_status = ""
    if v_image_url:
        image_status = "\n✅ <b>Изображение загружено!</b>\n"
    gemini_hint = ""
    if clamped_model == "gemini_omni":
        gemini_hint = (
            "\n🔷 <b>Gemini Omni:</b> Audio ID и Character ID не обязательны. "
            "Можно просто загрузить фото-рефы и отправить промпт.\n"
        )

    preview_data = {**data, "v_type": "imgtxt", "v_model": clamped_model}
    text = (
        "🎬 <b>Создание видео</b>\n\n"
        f"{_format_video_settings(preview_data)}\n"
        f"{image_status}\n"
        f"{gemini_hint}"
        "<b>Загрузите стартовое изображение</b>\n"
        "Отправьте фото, которое станет первым кадром видео,\n"
        "а затем введите промпт для генерации.\n"
        "<i>Пример: птица летит в небе, волны накатывают на берег.</i>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_create_video_keyboard(
            current_v_type="imgtxt",
            current_model=clamped_model,
            current_duration=ui["current_duration"],
            current_ratio=ui["current_ratio"],
            current_mode=ui["current_mode"],
            current_orientation=ui["current_orientation"],
            current_grok_mode=ui["current_grok_mode"],
            current_hailuo_resolution=ui["current_hailuo_resolution"],
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    # Не меняем состояние - оставляем waiting_for_input для приёма и фото, и текста
    # State will be waiting_for_input from previous handler


@router.callback_query(F.data == "v_type_video")
async def handle_v_type_video(callback: types.CallbackQuery, state: FSMContext):
    """Выбор типа генерации: видео+текст - запрашиваем несколько видео референсов"""
    from bot.database import get_user_credits

    user_credits = await get_user_credits(callback.from_user.id)

    data = await state.get_data()
    ui = _get_video_ui_state(data)
    clamped_model = _clamp_model_for_type(ui["current_model"], "video")
    await state.update_data(v_type="video", v_model=clamped_model)
    max_refs = 1 if clamped_model == "gemini_omni" else 5

    text = (
        "🎬 <b>Видео + Текст → Видео</b>\n\n"
        f"🪙 Баланс: <code>{user_credits}</code>\n\n"
        "<b>Шаг 1: загрузка видео-референсов</b>\n"
        + (
            "Для HappyHorse Edit нужно загрузить минимум одно видео.\n\n"
            if clamped_model == "happyhorse_edit"
            else f"Это опционально, можно добавить до {max_refs} коротких видео.\n\n"
        )
        + "Они помогут передать:\n"
        + "• стиль движения\n"
        + "• характер камеры\n"
        + "• атмосферу сцены\n\n"
        + "После загрузки нажмите «Продолжить» или «Пропустить»."
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_reference_videos_upload_keyboard(0, max_refs, "video_new"),
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.uploading_reference_videos)
    await callback.answer()


@router.callback_query(F.data == "vid_ref_skip_new")
async def handle_vid_ref_skip_new(callback: types.CallbackQuery, state: FSMContext):
    """Пропускает загрузку видео референсов для video+text"""
    await state.update_data(v_reference_videos=[])
    data = await state.get_data()
    if data.get("v_model") == "gemini_omni":
        await _show_gemini_omni_prompt_screen(callback.message, state)
        await callback.answer()
        return
    await _show_video_creation_screen(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "vid_ref_continue_new")
async def handle_vid_ref_continue_new(callback: types.CallbackQuery, state: FSMContext):
    """Продолжает после загрузки видео референсов"""
    data = await state.get_data()
    if data.get("v_model") == "gemini_omni":
        await _show_gemini_omni_prompt_screen(callback.message, state)
        await callback.answer()
        return
    await _show_video_creation_screen(callback.message, state)
    await callback.answer()


@router.callback_query(F.data.startswith("v_model_"))
async def handle_v_model(callback: types.CallbackQuery, state: FSMContext):
    """Generic handler for all video model selections"""
    model = callback.data.replace("v_model_", "")
    await _apply_video_model_selection(callback, state, model)


@router.callback_query(F.data.startswith("video_model_"))
async def handle_video_model_legacy(callback: types.CallbackQuery, state: FSMContext):
    """Legacy handler for get_video_models_inline_keyboard callbacks"""
    model = callback.data.replace("video_model_", "")
    await _apply_video_model_selection(callback, state, model)


@router.callback_query(F.data.startswith("video_gen_model_"))
async def handle_video_generation_model_legacy(
    callback: types.CallbackQuery, state: FSMContext
):
    """Legacy handler for get_video_generation_model_keyboard callbacks"""
    model = callback.data.replace("video_gen_model_", "")
    await _apply_video_model_selection(callback, state, model)


@router.callback_query(F.data.startswith("opt_v_model_"))
async def handle_video_options_model_legacy(
    callback: types.CallbackQuery, state: FSMContext
):
    """Legacy handler for opt_v_model_* callbacks"""
    model = callback.data.replace("opt_v_model_", "")
    await _apply_video_model_selection(callback, state, model)


@router.callback_query(F.data.startswith("grok_mode_"))
async def handle_grok_mode(callback: types.CallbackQuery, state: FSMContext):
    """Handler for Grok Imagine mode selection (normal/fun/spicy)"""
    mode = callback.data.replace("grok_mode_", "")
    data = await state.get_data()
    video_options = data.get("video_options", {})
    video_options["mode"] = mode
    await state.update_data(grok_mode=mode, video_options=video_options)
    await _show_video_creation_screen(callback, state)
    await callback.answer(f"Режим Grok: {mode.title()}")


@router.callback_query(F.data.startswith("hailuo_res_"))
async def handle_hailuo_resolution(callback: types.CallbackQuery, state: FSMContext):
    """Handler for Hailuo resolution selection (768P / 1080P)"""
    res_map = {"hailuo_res_768p": "768P", "hailuo_res_1080p": "1080P"}
    resolution = res_map.get(callback.data, "768P")
    data = await state.get_data()
    video_options = data.get("video_options", {})
    video_options["resolution"] = resolution
    await state.update_data(hailuo_resolution=resolution, video_options=video_options)
    await _show_video_creation_screen(callback, state)
    await callback.answer(f"Разрешение: {resolution}")


@router.callback_query(F.data.startswith("vopt_"))
async def handle_video_option(callback: types.CallbackQuery, state: FSMContext):
    """Generic video model option selection."""
    data = await state.get_data()
    model = data.get("v_model", "v3_std")
    config = get_video_model_config(model)
    raw_option = callback.data.replace("vopt_", "", 1)
    option_name = None
    raw_value = None
    for candidate in config.get("options", {}):
        prefix = f"{candidate}_"
        if raw_option.startswith(prefix):
            option_name = candidate
            raw_value = raw_option[len(prefix) :]
            break
    if not option_name:
        await callback.answer("Некорректная опция", show_alert=True)
        return
    allowed_values = config.get("options", {}).get(option_name)
    if not allowed_values:
        await callback.answer("Опция недоступна для этой модели", show_alert=True)
        return

    value = None
    for candidate in allowed_values:
        if str(candidate).lower() == raw_value:
            value = candidate
            break
    if value is None:
        await callback.answer("Некорректное значение", show_alert=True)
        return

    video_options = data.get("video_options", {})
    video_options[option_name] = value
    updates = {"video_options": normalize_video_options(model, video_options)}
    if option_name == "mode":
        updates["grok_mode"] = value
    if option_name == "resolution" and model.startswith("hailuo"):
        updates["hailuo_resolution"] = value
    if option_name == "motion_quality":
        updates["v_mode"] = value
    if option_name == "character_orientation":
        updates["v_orientation"] = value
    await state.update_data(**updates)
    await _show_video_creation_screen(callback, state)
    await callback.answer()


async def _apply_video_model_selection(
    callback: types.CallbackQuery, state: FSMContext, model: str
):
    """Apply video model selection across all keyboard variants."""
    data = await state.get_data()
    ui = _get_video_ui_state(data)
    current_v_type = ui["current_v_type"]
    current_duration = ui["current_duration"]
    current_ratio = ui["current_ratio"]

    # Set default grok_mode for grok_imagine
    if model == "grok_imagine":
        await state.update_data(grok_mode="normal")

    # WanX LoRA is text-to-video only, so we force the UI into text mode
    # to expose aspect ratio and duration controls immediately.
    if model.startswith("wanx"):
        current_v_type = "text"

    video_options = normalize_video_options(model, data.get("video_options", {}))
    model_config = get_video_model_config(model)
    durations = model_config.get("durations") or []
    ratios = model_config.get("aspect_ratios")
    if durations and current_duration not in durations:
        current_duration = durations[0]
    if ratios and current_ratio not in ratios:
        current_ratio = ratios[0]

    await state.update_data(
        v_model=model,
        v_type=current_v_type,
        v_duration=current_duration,
        v_ratio=current_ratio,
        video_options=video_options,
    )
    if model.startswith("wanx"):
        await state.update_data(
            wanx_lora_settings=[{"lora_type": "nsfw-general", "lora_strength": 1.0}]
        )

    if model.startswith("wanx"):
        await callback.message.edit_text(
            "🎬 <b>WanX LoRA</b>"
            "Выберите формат и длительность для генерации:\n"
            "• 📐 Доступные aspect ratio\n"
            "• ⏱ Доступное время"
            "После выбора параметров введите промпт.",
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=model,
                current_duration=current_duration,
                current_ratio=current_ratio,
                current_mode=ui["current_mode"],
                current_orientation=ui["current_orientation"],
                current_grok_mode=data.get("grok_mode", "normal"),
                current_hailuo_resolution=data.get("hailuo_resolution", "768P"),
            ),
            parse_mode="HTML",
        )
    else:
        await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data.startswith("vratio_"))
async def handle_dynamic_video_ratio(callback: types.CallbackQuery, state: FSMContext):
    ratio = callback.data.replace("vratio_", "", 1).replace("_", ":")
    await state.update_data(v_ratio=ratio)
    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data.startswith("vdur_"))
async def handle_dynamic_video_duration(
    callback: types.CallbackQuery, state: FSMContext
):
    duration = int(callback.data.replace("vdur_", "", 1))
    await state.update_data(v_duration=duration)
    await _show_video_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data == "gemini_omni_menu")
async def show_gemini_omni_menu(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await _prepare_gemini_omni_context(state, data)
    data = await state.get_data()
    await _edit_or_send_gemini_omni_screen(
        callback.message,
        _format_omni_context(data),
        reply_markup=_gemini_omni_keyboard_from_data(data),
    )
    await callback.answer()


async def _prepare_gemini_omni_context(state: FSMContext, data: dict | None = None):
    data = data or await state.get_data()
    ui = _get_video_ui_state(data)
    model_config = get_video_model_config("gemini_omni")
    duration = ui["current_duration"]
    if duration not in model_config["durations"]:
        duration = model_config["durations"][0]
    ratio = ui["current_ratio"]
    if ratio not in model_config["aspect_ratios"]:
        ratio = model_config["aspect_ratios"][0]
    await state.update_data(
        generation_type="video",
        v_model="gemini_omni",
        v_type=ui["current_v_type"],
        v_duration=duration,
        v_ratio=ratio,
        video_options=normalize_video_options("gemini_omni", data.get("video_options")),
    )


async def _edit_or_send_gemini_omni_screen(
    message: types.Message,
    text: str,
    reply_markup=None,
):
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        logger.warning("Cannot edit Gemini Omni message: %s", e)
        await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        logger.warning("Cannot edit Gemini Omni message: %s", e)
        await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")


async def _show_gemini_omni_prompt_screen(
    message: types.Message,
    state: FSMContext,
    prompt: str | None = None,
):
    data = await state.get_data()
    await _prepare_gemini_omni_context(state, data)
    data = await state.get_data()
    video_options = normalize_video_options("gemini_omni", data.get("video_options"))
    effective_images = _get_gemini_omni_effective_image_urls(data)
    videos_count = len(data.get("v_reference_videos", []))
    text = prompt or (
        "🎬 <b>Gemini Omni: запуск видео</b>\n\n"
        "Напишите промпт следующим сообщением — это и запустит генерацию.\n\n"
        "<b>Пример:</b>\n"
        "<code>Милое 4-секундное видео: синяя бабочка летит над цветами, "
        "мягкий солнечный свет, плавное приближение камеры, без текста на экране.</code>\n\n"
        f"🎙 Голоса: <code>{len(data.get('omni_audio_ids', []))}</code>/{GEMINI_OMNI_MAX_AUDIO_IDS}\n"
        f"🧍 Персонажи: <code>{len(data.get('omni_character_ids', []))}</code>/{GEMINI_OMNI_MAX_CHARACTER_IDS}\n"
        f"🖼 Фото: <code>{len(effective_images)}</code>/{GEMINI_OMNI_MAX_IMAGES}\n"
        f"📹 Видео: <code>{videos_count}</code>/1\n"
        f"⏱ Время: <code>{data.get('v_duration', 4)} сек"
        f"{' (не влияет при видео-рефе)' if videos_count else ''}</code>\n"
        f"💎 Качество: <code>{video_options.get('resolution', '720p')}</code>\n"
        f"📐 Формат: <code>{data.get('v_ratio', '16:9')}</code>\n\n"
        "Голос, персонаж, фото и видео-рефы будут использованы автоматически, если вы их добавили."
    )
    await _edit_or_send_gemini_omni_screen(
        message,
        text,
        reply_markup=_gemini_omni_keyboard_from_data(data),
    )
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.callback_query(F.data == "omni_start_video")
async def start_gemini_omni_video(callback: types.CallbackQuery, state: FSMContext):
    await _show_gemini_omni_prompt_screen(callback.message, state)
    await callback.answer("Отправьте промпт")


@router.callback_query(F.data == "omni_add_photo_video")
async def show_gemini_omni_photo_video_flow(
    callback: types.CallbackQuery, state: FSMContext
):
    data = await state.get_data()
    await _prepare_gemini_omni_context(state, data)
    await state.update_data(v_type="imgtxt", v_model="gemini_omni")
    data = await state.get_data()
    await _edit_or_send_gemini_omni_screen(
        callback.message,
        "🖼+📹 <b>Gemini Omni: фото + видео</b>\n\n"
        "Лучший порядок:\n"
        "1. Добавьте фото: объект, персонаж, продукт, стиль или первый кадр.\n"
        "2. Добавьте одно видео: движение, камера, жесты или атмосфера.\n"
        "3. Нажмите <b>Запустить видео</b> и напишите промпт.\n\n"
        "Kie считает входы так: фото=1, видео=2, Character ID=1. Всего до "
        f"<code>{GEMINI_OMNI_MAX_INPUT_UNITS}</code> единиц.\n\n"
        f"{_format_omni_context(data)}",
        reply_markup=_gemini_omni_keyboard_from_data(data),
    )
    await state.set_state(GenerationStates.waiting_for_video_prompt)
    await callback.answer()


@router.callback_query(F.data == "omni_add_photo")
async def ask_gemini_omni_photo(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await _prepare_gemini_omni_context(state, data)
    await state.update_data(
        generation_type="video",
        v_type="imgtxt",
        v_model="gemini_omni",
    )
    data = await state.get_data()
    await _edit_or_send_gemini_omni_screen(
        callback.message,
        _format_omni_context(data),
        reply_markup=_gemini_omni_keyboard_from_data(data),
    )
    await callback.message.answer(
        "🖼 <b>Добавить фото в Gemini Omni</b>\n\n"
        "Отправьте одно или несколько фото. Первое станет основным кадром, остальные референсами.\n"
        "Можно затем добавить видео-референс: Gemini Omni отправит фото и видео вместе.\n"
        "Когда медиа добавлены, отправьте промпт текстом.",
        reply_markup=_gemini_omni_keyboard_from_data(data),
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_photo_reference)
    await callback.answer()


@router.message(
    GenerationStates.waiting_for_omni_photo_reference,
    F.photo
    | (
        F.document & F.document.mime_type.in_(["image/jpeg", "image/png", "image/webp"])
    ),
)
async def save_gemini_omni_photo_reference(
    message: types.Message, state: FSMContext
):
    """Save photos from the standalone Gemini Omni menu into Omni video context."""
    data = await state.get_data()
    effective_images = _get_gemini_omni_effective_image_urls(data)
    if len(effective_images) >= GEMINI_OMNI_MAX_IMAGES:
        await message.answer(
            f"❌ Gemini Omni принимает до {GEMINI_OMNI_MAX_IMAGES} фото. "
            "Отправьте промпт или очистите референсы.",
            reply_markup=_gemini_omni_keyboard_from_data(data),
            parse_mode="HTML",
        )
        return

    if message.photo:
        image_obj = message.photo[-1]
        file_ext = "jpg"
    else:
        image_obj = message.document
        mime_type = message.document.mime_type
        file_ext = {
            "image/jpeg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
        }.get(mime_type, "png")

    file = await message.bot.get_file(image_obj.file_id)
    image_bytes = await message.bot.download_file(file.file_path)
    image_data = image_bytes.read()

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_data))
        width, height = img.size
        if width < 300 or height < 300:
            await message.answer(
                f"❌ Изображение слишком маленькое: {width}×{height}\n"
                "Загрузите фото не менее 300×300 px.",
                parse_mode="HTML",
            )
            return
    except Exception as e:
        logger.error("Gemini Omni image validation failed: %s", e)
        await message.answer("❌ Не удалось обработать изображение. Попробуйте другое.")
        return

    image_url = save_uploaded_file(image_data, file_ext, is_reference=True)
    if not image_url:
        await message.answer("❌ Не удалось сохранить фото. Попробуйте ещё раз.")
        return

    reference_images = data.get("reference_images", [])
    if data.get("v_image_url"):
        reference_images.append(image_url)
        await state.update_data(reference_images=reference_images)
        added_as = "референс"
    else:
        await state.update_data(v_image_url=image_url)
        added_as = "основное фото"

    await state.update_data(
        generation_type="video",
        v_type="imgtxt",
        v_model="gemini_omni",
    )
    data = await state.get_data()
    current_count = len(_get_gemini_omni_effective_image_urls(data))
    await message.answer(
        f"✅ Фото добавлено как {added_as}: "
        f"<code>{current_count}/{GEMINI_OMNI_MAX_IMAGES}</code>\n\n"
        "Отправьте ещё фото или напишите промпт для запуска.",
        reply_markup=_gemini_omni_keyboard_from_data(data),
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_photo_reference)


@router.message(GenerationStates.waiting_for_omni_photo_reference, F.text)
async def handle_gemini_omni_photo_reference_prompt(
    message: types.Message, state: FSMContext
):
    await handle_video_prompt_text(message, state)


@router.callback_query(F.data == "omni_add_video")
async def ask_gemini_omni_video_reference(
    callback: types.CallbackQuery, state: FSMContext
):
    data = await state.get_data()
    await _prepare_gemini_omni_context(state, data)
    await state.update_data(v_type="video", v_model="gemini_omni")
    current_count = len(data.get("v_reference_videos", []))
    await _edit_or_send_gemini_omni_screen(
        callback.message,
        "📹 <b>Добавить видео-референс Gemini Omni</b>\n\n"
        "Отправьте короткое видео до 20MB. Gemini Omni использует максимум 1 видео-референс.\n"
        "Можно также добавить фото: Gemini Omni отправит фото и видео вместе.\n"
        "После загрузки нажмите <b>Продолжить</b> или отправьте промпт после возврата.",
        reply_markup=get_reference_videos_upload_keyboard(current_count, 1, "video_new"),
    )
    await state.set_state(GenerationStates.uploading_reference_videos)
    await callback.answer()


@router.callback_query(F.data == "omni_use_video")
async def use_gemini_omni_video(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    ui = _get_video_ui_state(data)
    model_config = get_video_model_config("gemini_omni")
    duration = ui["current_duration"]
    if duration not in model_config["durations"]:
        duration = model_config["durations"][0]
    ratio = ui["current_ratio"]
    if ratio not in model_config["aspect_ratios"]:
        ratio = model_config["aspect_ratios"][0]
    await state.update_data(
        generation_type="video",
        v_model="gemini_omni",
        v_type=ui["current_v_type"],
        v_duration=duration,
        v_ratio=ratio,
        video_options=normalize_video_options("gemini_omni", data.get("video_options")),
    )
    await _show_gemini_omni_prompt_screen(callback.message, state)
    await callback.answer("Отправьте промпт")


@router.callback_query(F.data == "omni_clear_refs")
async def clear_gemini_omni_refs(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(
        omni_audio_ids=[],
        omni_character_ids=[],
        omni_character_source_images=[],
        omni_character_image_url=None,
        v_image_url=None,
        reference_images=[],
        v_reference_videos=[],
    )
    data = await state.get_data()
    await _edit_or_send_gemini_omni_screen(
        callback.message,
        _format_omni_context(data),
        reply_markup=_gemini_omni_keyboard_from_data(data),
    )
    await callback.answer("Omni ID очищены")


@router.callback_query(F.data == "omni_add_audio_id")
async def ask_gemini_omni_audio_id(callback: types.CallbackQuery, state: FSMContext):
    await _edit_or_send_gemini_omni_screen(
        callback.message,
        "🎙 <b>Добавить Audio ID</b>\n\n"
        "Отправьте ID, полученный из Gemini Omni Audio.\n"
        f"Для видео можно добавить до {GEMINI_OMNI_MAX_AUDIO_IDS} Audio ID.\n\n"
        "Если ID ещё нет, нажмите <b>Назад → Создать голос</b> и просто опишите голос.",
        reply_markup=get_back_keyboard("gemini_omni_menu"),
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_omni_audio_id)


@router.callback_query(F.data == "omni_add_character_id")
async def ask_gemini_omni_character_id(callback: types.CallbackQuery, state: FSMContext):
    await _edit_or_send_gemini_omni_screen(
        callback.message,
        "🧍 <b>Добавить Character ID</b>\n\n"
        "Отправьте ID персонажа, полученный из Gemini Omni Character.\n"
        f"Для видео можно использовать до {GEMINI_OMNI_MAX_CHARACTER_IDS} Character ID.\n\n"
        "Если создаёте персонажа здесь, я сохраню исходное фото и добавлю его в видео автоматически.",
        reply_markup=get_back_keyboard("gemini_omni_menu"),
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_omni_character_id)


@router.callback_query(F.data == "omni_set_seed")
async def ask_gemini_omni_seed(callback: types.CallbackQuery, state: FSMContext):
    await _edit_or_send_gemini_omni_screen(
        callback.message,
        "🌱 <b>Seed видео Gemini Omni</b>\n\n"
        "Отправьте число от <code>0</code> до <code>2147483647</code> "
        "или <code>auto</code>, чтобы убрать фиксированный seed.\n\n"
        "Если вы отправите описание голоса, я пойму это и создам Omni Audio.",
        reply_markup=get_back_keyboard("gemini_omni_menu"),
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_omni_seed)


def _build_omni_choice_keyboard(prefix: str, values: list, current_value):
    keyboard = []
    row = []
    for value in values:
        check = "✅ " if value == current_value else ""
        row.append(
            types.InlineKeyboardButton(
                text=f"{check}{value}",
                callback_data=f"{prefix}_{str(value).replace(':', '_')}",
            )
        )
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append(
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="gemini_omni_menu")]
    )
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.callback_query(F.data == "omni_choose_duration")
async def choose_gemini_omni_duration(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_duration = int(data.get("v_duration", 4))
    await _edit_or_send_gemini_omni_screen(
        callback.message,
        "⏱ <b>Время Gemini Omni</b>\n\n"
        "Выберите длительность видео. Доступно по Kie docs: 4, 6, 8 или 10 секунд.\n"
        "Если добавлен видео-референс, модель может сама определить длительность результата.",
        reply_markup=_build_omni_choice_keyboard(
            "omni_duration", [4, 6, 8, 10], current_duration
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("omni_duration_"))
async def set_gemini_omni_duration(callback: types.CallbackQuery, state: FSMContext):
    duration = int(callback.data.replace("omni_duration_", "", 1))
    await state.update_data(v_duration=duration)
    data = await state.get_data()
    await _edit_or_send_gemini_omni_screen(
        callback.message,
        _format_omni_context(data),
        reply_markup=_gemini_omni_keyboard_from_data(data),
    )
    await callback.answer(f"Время: {duration} сек")


@router.callback_query(F.data == "omni_choose_resolution")
async def choose_gemini_omni_resolution(
    callback: types.CallbackQuery, state: FSMContext
):
    data = await state.get_data()
    video_options = normalize_video_options("gemini_omni", data.get("video_options"))
    current_resolution = video_options.get("resolution", "720p")
    await _edit_or_send_gemini_omni_screen(
        callback.message,
        "💎 <b>Качество Gemini Omni</b>\n\n"
        "Выберите разрешение результата. Чем выше качество, тем дольше может идти генерация.",
        reply_markup=_build_omni_choice_keyboard(
            "omni_resolution", ["720p", "1080p", "4k"], current_resolution
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("omni_resolution_"))
async def set_gemini_omni_resolution(callback: types.CallbackQuery, state: FSMContext):
    resolution = callback.data.replace("omni_resolution_", "", 1)
    video_options = (await state.get_data()).get("video_options", {})
    video_options["resolution"] = resolution
    await state.update_data(
        video_options=normalize_video_options("gemini_omni", video_options)
    )
    data = await state.get_data()
    await _edit_or_send_gemini_omni_screen(
        callback.message,
        _format_omni_context(data),
        reply_markup=_gemini_omni_keyboard_from_data(data),
    )
    await callback.answer(f"Качество: {resolution}")


@router.callback_query(F.data == "omni_choose_ratio")
async def choose_gemini_omni_ratio(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_ratio = data.get("v_ratio", "16:9")
    await _edit_or_send_gemini_omni_screen(
        callback.message,
        "📐 <b>Формат Gemini Omni</b>\n\n"
        "Выберите соотношение сторон видео.",
        reply_markup=_build_omni_choice_keyboard(
            "omni_ratio", ["16:9", "9:16"], current_ratio
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("omni_ratio_"))
async def set_gemini_omni_ratio(callback: types.CallbackQuery, state: FSMContext):
    ratio = callback.data.replace("omni_ratio_", "", 1).replace("_", ":")
    await state.update_data(v_ratio=ratio)
    data = await state.get_data()
    await _edit_or_send_gemini_omni_screen(
        callback.message,
        _format_omni_context(data),
        reply_markup=_gemini_omni_keyboard_from_data(data),
    )
    await callback.answer(f"Формат: {ratio}")


@router.callback_query(F.data == "omni_create_audio")
async def ask_gemini_omni_audio(callback: types.CallbackQuery, state: FSMContext):
    await _edit_or_send_gemini_omni_screen(
        callback.message,
        "🎙 <b>Создание Gemini Omni Audio</b>\n\n"
        "Просто опишите голос одним сообщением, например:\n"
        "<code>писклявый милый голос</code>\n\n"
        "Для точной настройки можно отправить параметры:\n"
        "<code>audio_id=achernar\n"
        "name=Calm narrator\n"
        "voice_description=calm, clear, friendly male voice\n"
        "example_dialogue=Hello, I am your narrator</code>\n\n"
        "Базовые голоса: achernar, achird, algenib, algieba, alnilam, aoede, "
        "autonoe, callirrhoe, charon, despina, enceladus, erinome, fenrir, "
        "gacrux, iapetus, kore, laomedeia, leda, orus, puck, zephyr.",
        reply_markup=get_back_keyboard("gemini_omni_menu"),
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_omni_audio_details)


@router.callback_query(F.data == "omni_create_character")
async def ask_gemini_omni_character_image(
    callback: types.CallbackQuery, state: FSMContext
):
    await _edit_or_send_gemini_omni_screen(
        callback.message,
        "🧍 <b>Создание Gemini Omni Character</b>\n\n"
        "Отправьте одно фото персонажа.\n"
        "Можно сразу с подписью, например: <code>синяя бабочка в тропическом лесу</code>.\n\n"
        "Если подписи нет, я попрошу описание следующим сообщением.",
        reply_markup=get_back_keyboard("gemini_omni_menu"),
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_omni_character_image)


@router.message(GenerationStates.waiting_for_omni_audio_id, F.text)
async def save_gemini_omni_audio_id(message: types.Message, state: FSMContext):
    audio_id = message.text.strip()
    if not audio_id:
        await message.answer("Отправьте непустой Audio ID.")
        return
    if audio_id.lower() in GEMINI_OMNI_BASE_VOICES:
        await message.answer(
            "❌ Это базовый голос Gemini Omni, а не готовый Audio ID.\n\n"
            "Сначала нажмите <b>«Создать голос»</b>, выберите этот базовый голос "
            "как <code>audio_id=...</code>, и используйте ID из ответа.",
            reply_markup=_gemini_omni_keyboard_from_data(await state.get_data()),
            parse_mode="HTML",
        )
        await state.set_state(GenerationStates.waiting_for_video_prompt)
        return
    data = await state.get_data()
    audio_ids = data.get("omni_audio_ids", [])
    if audio_id not in audio_ids:
        audio_ids.append(audio_id)
    audio_ids = audio_ids[-GEMINI_OMNI_MAX_AUDIO_IDS:]
    await state.update_data(omni_audio_ids=audio_ids)
    await message.answer(
        f"✅ Audio ID добавлен: <code>{html.escape(audio_id)}</code>\n"
        f"Всего голосов: <code>{len(audio_ids)}</code>/{GEMINI_OMNI_MAX_AUDIO_IDS}",
        reply_markup=_gemini_omni_keyboard_from_data(await state.get_data()),
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.message(GenerationStates.waiting_for_omni_character_id, F.text)
async def save_gemini_omni_character_id(message: types.Message, state: FSMContext):
    character_id = message.text.strip()
    if not character_id:
        await message.answer("Отправьте непустой Character ID.")
        return
    data = await state.get_data()
    character_ids = data.get("omni_character_ids", [])
    if character_id not in character_ids:
        character_ids.append(character_id)
    character_ids = character_ids[-GEMINI_OMNI_MAX_CHARACTER_IDS:]
    await state.update_data(omni_character_ids=character_ids)
    await message.answer(
        f"✅ Character ID добавлен: <code>{html.escape(character_id)}</code>\n"
        f"Всего персонажей: <code>{len(character_ids)}</code>/{GEMINI_OMNI_MAX_CHARACTER_IDS}",
        reply_markup=_gemini_omni_keyboard_from_data(await state.get_data()),
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_video_prompt)


@router.message(GenerationStates.waiting_for_omni_seed, F.text)
async def save_gemini_omni_seed(message: types.Message, state: FSMContext):
    raw_text = message.text.strip()
    raw_seed = raw_text.lower()
    data = await state.get_data()
    video_options = data.get("video_options", {})
    if raw_seed in {"auto", "none", "нет", "авто", "-"}:
        video_options["seed"] = None
        text = "✅ Seed сброшен: <code>auto</code>"
    else:
        try:
            seed = int(raw_seed)
        except ValueError:
            if _looks_like_voice_description(raw_text):
                await _create_gemini_omni_audio_from_text(
                    message,
                    state,
                    raw_text,
                    intro_text="Похоже, это описание голоса. Создаю Omni Audio...",
                )
                return
            await message.answer(
                "❌ Seed должен быть числом или <code>auto</code>.",
                parse_mode="HTML",
            )
            return
        if seed < 0 or seed > 2147483647:
            await message.answer("❌ Seed должен быть от 0 до 2147483647.")
            return
        video_options["seed"] = seed
        text = f"✅ Seed установлен: <code>{seed}</code>"
    await state.update_data(
        video_options=normalize_video_options("gemini_omni", video_options)
    )
    await message.answer(
        text,
        reply_markup=_gemini_omni_keyboard_from_data(await state.get_data()),
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_video_prompt)


async def _create_and_store_gemini_omni_audio(
    message: types.Message,
    state: FSMContext,
    audio_id: str,
    name: str,
    voice_description: str,
    example_dialogue: str = "",
    intro_text: str = "🎙 Создаю Omni Audio...",
) -> bool:
    audio_id = audio_id.lower().strip()
    name = name.strip()
    voice_description = voice_description.strip()
    example_dialogue = example_dialogue.strip()

    if audio_id not in GEMINI_OMNI_BASE_VOICES:
        await message.answer(
            "❌ Неизвестный базовый audio_id. Например: <code>achernar</code>.",
            parse_mode="HTML",
        )
        return False
    if not name:
        await message.answer("❌ Укажите <code>name=...</code>", parse_mode="HTML")
        return False

    wait_msg = await message.answer(intro_text)
    result = await gemini_omni_service.create_audio(
        audio_id=audio_id,
        name=name,
        voice_description=voice_description,
        example_dialogue=example_dialogue,
    )
    try:
        await wait_msg.delete()
    except TelegramBadRequest:
        pass
    if not result:
        await message.answer("❌ Не удалось создать Omni Audio.")
        await state.set_state(GenerationStates.waiting_for_video_prompt)
        return False

    data = await state.get_data()
    audio_ids = data.get("omni_audio_ids", [])
    if result["audio_id"] not in audio_ids:
        audio_ids.append(result["audio_id"])
    audio_ids = audio_ids[-GEMINI_OMNI_MAX_AUDIO_IDS:]
    await state.update_data(omni_audio_ids=audio_ids)
    logger.info(
        "Stored Gemini Omni audio id for user %s: %s",
        message.from_user.id,
        result["audio_id"],
    )
    await message.answer(
        "✅ <b>Omni Audio создан</b>\n\n"
        f"Audio ID: <code>{html.escape(result['audio_id'])}</code>\n"
        f"Название: <code>{html.escape(str(result.get('name') or name))}</code>\n"
        f"База: <code>{html.escape(audio_id)}</code>\n\n"
        f"Я добавил этот Audio ID в текущую Omni-видеозадачу "
        f"(<code>{len(audio_ids)}</code>/{GEMINI_OMNI_MAX_AUDIO_IDS}).",
        reply_markup=_gemini_omni_keyboard_from_data(await state.get_data()),
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_video_prompt)
    return True


async def _create_gemini_omni_audio_from_text(
    message: types.Message,
    state: FSMContext,
    description: str,
    intro_text: str = "🎙 Создаю Omni Audio...",
) -> bool:
    return await _create_and_store_gemini_omni_audio(
        message=message,
        state=state,
        audio_id=_pick_gemini_omni_base_voice(description),
        name=_make_gemini_omni_voice_name(description),
        voice_description=description,
        example_dialogue="",
        intro_text=intro_text,
    )


@router.message(GenerationStates.waiting_for_omni_audio_details, F.text)
async def create_gemini_omni_audio(message: types.Message, state: FSMContext):
    fields = _parse_key_value_lines(message.text)
    positional = fields.get("_positional", [])
    named_fields = {
        "audio_id",
        "name",
        "voice_description",
        "description",
        "example_dialogue",
        "dialogue",
    }
    has_named_fields = any(key in fields for key in named_fields)
    if not has_named_fields and not (
        positional and positional[0].lower() in GEMINI_OMNI_BASE_VOICES
    ):
        await _create_gemini_omni_audio_from_text(message, state, message.text)
        return

    audio_id = (fields.get("audio_id") or (positional[0] if positional else "")).lower()
    name = fields.get("name") or (positional[1] if len(positional) > 1 else "")
    voice_description = (
        fields.get("voice_description") or fields.get("description") or ""
    )
    example_dialogue = fields.get("example_dialogue") or fields.get("dialogue") or ""

    if not voice_description and positional and audio_id in GEMINI_OMNI_BASE_VOICES:
        voice_description = " ".join(positional[2:])
    if not audio_id and voice_description:
        audio_id = _pick_gemini_omni_base_voice(voice_description)
    if not name:
        name = _make_gemini_omni_voice_name(voice_description or message.text)

    await _create_and_store_gemini_omni_audio(
        message=message,
        state=state,
        audio_id=audio_id,
        name=name,
        voice_description=voice_description,
        example_dialogue=example_dialogue,
    )


@router.message(GenerationStates.waiting_for_omni_character_image, F.photo)
async def save_gemini_omni_character_image(message: types.Message, state: FSMContext):
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    image_bytes = await message.bot.download_file(file.file_path)
    image_url = save_uploaded_file(image_bytes.read(), "png", is_reference=True)
    if not image_url:
        await message.answer("❌ Не удалось сохранить фото персонажа.")
        return
    await state.update_data(omni_character_image_url=image_url)
    if message.caption and message.caption.strip():
        await _create_and_store_gemini_omni_character(
            message=message,
            state=state,
            image_url=image_url,
            description=message.caption,
            character_name=_make_gemini_omni_character_name(message.caption),
        )
        return
    await message.answer(
        "✅ Фото персонажа загружено.\n\n"
        "Теперь просто опишите персонажа одним сообщением, например:\n"
        "<code>синяя бабочка в тропическом лесу</code>\n\n"
        "Можно подробнее: внешний вид, стиль, настроение, одежда или роль.",
        reply_markup=get_back_keyboard("gemini_omni_menu"),
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_omni_character_details)


async def _create_and_store_gemini_omni_character(
    message: types.Message,
    state: FSMContext,
    image_url: str,
    description: str,
    character_name: str = "",
) -> bool:
    description = description.strip()
    character_name = character_name.strip() or _make_gemini_omni_character_name(
        description
    )
    if not description:
        await message.answer("❌ Опишите персонажа одним сообщением.")
        return False

    data = await state.get_data()
    wait_msg = await message.answer("🧍 Создаю Omni Character...")
    result = await gemini_omni_service.create_character(
        description=description,
        image_url=image_url,
        character_name=character_name,
        audio_ids=data.get("omni_audio_ids", []),
    )
    try:
        await wait_msg.delete()
    except TelegramBadRequest:
        pass
    if not result:
        await message.answer("❌ Не удалось создать Omni Character.")
        await state.set_state(GenerationStates.waiting_for_video_prompt)
        return False

    character_ids = data.get("omni_character_ids", [])
    character_ids.append(result["character_id"])
    character_ids = character_ids[-GEMINI_OMNI_MAX_CHARACTER_IDS:]
    source_images = data.get("omni_character_source_images", [])
    if image_url not in source_images:
        source_images.append(image_url)
    source_images = source_images[-GEMINI_OMNI_MAX_CHARACTER_IDS:]
    await state.update_data(
        omni_character_ids=character_ids,
        omni_character_source_images=source_images,
    )
    await message.answer(
        "✅ <b>Omni Character создан</b>\n\n"
        f"Character ID: <code>{html.escape(result['character_id'])}</code>\n"
        f"Имя: <code>{html.escape(str(result.get('name') or character_name))}</code>\n\n"
        "Я добавил этого персонажа в текущую Omni-видеозадачу.",
        reply_markup=_gemini_omni_keyboard_from_data(await state.get_data()),
        parse_mode="HTML",
    )
    await state.set_state(GenerationStates.waiting_for_video_prompt)
    return True


@router.message(GenerationStates.waiting_for_omni_character_details, F.text)
async def create_gemini_omni_character(message: types.Message, state: FSMContext):
    data = await state.get_data()
    image_url = data.get("omni_character_image_url")
    if not image_url:
        await message.answer("❌ Сначала отправьте фото персонажа.")
        await state.set_state(GenerationStates.waiting_for_omni_character_image)
        return

    fields = _parse_key_value_lines(message.text)
    positional = fields.get("_positional", [])
    has_named_fields = any(
        key in fields for key in {"character_name", "name", "description", "descriptions"}
    )
    if has_named_fields:
        character_name = fields.get("character_name") or fields.get("name") or ""
        description = fields.get("description") or fields.get("descriptions") or (
            " ".join(positional) if positional else ""
        )
    else:
        description = message.text.strip()
        character_name = _make_gemini_omni_character_name(description)

    await _create_and_store_gemini_omni_character(
        message=message,
        state=state,
        image_url=image_url,
        description=description,
        character_name=character_name,
    )


# =============================================================================
# НОВЫЙ UX: МЕНЮ СОЗДАНИЯ ФОТО (get_create_image_keyboard)
# =============================================================================


async def _refresh_image_creation_screen(
    callback: types.CallbackQuery, state: FSMContext
) -> None:
    data = await state.get_data()
    img_count = data.get("img_count", 1)
    current_service, current_options, reference_images = await _sync_image_state(state)
    is_feed_retry = bool(data.get("feed_retry_task_id"))
    text = (
        _build_feed_retry_model_text(
            current_service,
            current_options,
            reference_images,
            data.get("feed_retry_prompt", ""),
            img_count,
        )
        if is_feed_retry
        else _build_image_creation_text(
            current_service,
            current_options,
            reference_images,
            img_count,
        )
    )
    markup = get_create_image_keyboard(
        current_service=current_service,
        current_ratio=current_options["aspect_ratio"],
        num_refs=len(reference_images),
        current_options=current_options,
        img_count=img_count,
        launch_callback_data="feed_retry_run" if is_feed_retry else None,
        launch_text="🚀 Запустить повтор",
        edit_prompt_callback_data="feed_retry_edit_prompt" if is_feed_retry else None,
        full_prompt_callback_data="feed_retry_full_prompt" if is_feed_retry else None,
    )
    if is_feed_retry:
        control_message_id = await _edit_feed_retry_control_message(callback, text, markup)
        if control_message_id:
            await state.update_data(feed_retry_control_message_id=control_message_id)
    else:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(F.data == "img_count_info")
async def handle_img_count_info(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer(
        "Выберите количество одновременных генераций (1-6)", show_alert=False
    )


@router.callback_query(F.data.startswith("img_count_"))
async def handle_img_count(callback: types.CallbackQuery, state: FSMContext):
    """Устанавливает количество одновременных генераций"""
    try:
        count = int(callback.data.replace("img_count_", ""))
        if count < 1 or count > 6:
            await callback.answer("❌ Допустимо от 1 до 6", show_alert=True)
            return
    except ValueError:
        await callback.answer("❌ Неверное значение", show_alert=True)
        return
    await state.update_data(img_count=count)
    await _refresh_image_creation_screen(callback, state)
    await callback.answer(f"✅ Будет запущено {count} генераций")
    data = await state.get_data()
    await state.set_state(
        GenerationStates.confirming_reference_images
        if data.get("feed_retry_task_id")
        else GenerationStates.waiting_for_input
    )


@router.callback_query(F.data.startswith("img_model_"))
async def handle_dynamic_image_model(callback: types.CallbackQuery, state: FSMContext):
    model_id = callback.data.replace("img_model_", "", 1)
    await _sync_image_state(state, model_id=model_id)
    await _refresh_image_creation_screen(callback, state)
    await callback.answer()
    data = await state.get_data()
    await state.set_state(
        GenerationStates.confirming_reference_images
        if data.get("feed_retry_task_id")
        else GenerationStates.waiting_for_input
    )


@router.callback_query(F.data.startswith("imgopt_"))
async def handle_dynamic_image_option(callback: types.CallbackQuery, state: FSMContext):
    payload = callback.data.replace("imgopt_", "", 1)
    prefix_map = {
        "aspect_ratio": "aspect_ratio_",
        "output_format": "output_format_",
        "resolution": "resolution_",
        "quality": "quality_",
        "nsfw_checker": "nsfw_checker_",
        "enable_pro": "enable_pro_",
        "rendering_speed": "rendering_speed_",
        "style": "style_",
        "expand_prompt": "expand_prompt_",
    }

    option_name = None
    raw_value = None
    for candidate, prefix in prefix_map.items():
        if payload.startswith(prefix):
            option_name = candidate
            raw_value = payload[len(prefix) :]
            break

    if option_name is None:
        await callback.answer("Неизвестная опция", show_alert=True)
        return

    if option_name in {"nsfw_checker", "expand_prompt", "enable_pro"}:
        value = raw_value == "on"
    elif option_name == "aspect_ratio":
        value = raw_value.replace("_", ":").upper().replace("AUTO", "auto")
    elif option_name == "output_format":
        value = raw_value.lower()
    elif option_name == "quality":
        value = raw_value.lower()
    elif option_name in {"rendering_speed", "style"}:
        value = raw_value.upper()
    else:
        value = raw_value.upper()

    await _sync_image_state(state, option_updates={option_name: value})
    await _refresh_image_creation_screen(callback, state)
    await callback.answer()
    data = await state.get_data()
    await state.set_state(
        GenerationStates.confirming_reference_images
        if data.get("feed_retry_task_id")
        else GenerationStates.waiting_for_input
    )


@router.callback_query(F.data == "model_nanobanana")
async def handle_model_nanobanana(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Nano Banana"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")
    reference_images = data.get("reference_images", [])
    ref_text = (
        f"📎 Референсов: <code>{len(reference_images)}</code>"
        if reference_images
        else ""
    )

    await state.update_data(img_service="nanobanana")

    text = (
        f"🖼 <b>Создание фото</b>"
        f"{ref_text}"
        f"✨ Модель: <code>nanobanana</code>\n"
        f"📐 Формат: <code>{current_ratio}</code>"
        f"<b>Введите промпт для генерации:</b>"
        f"Опишите что хотите создать:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_create_image_keyboard(
            current_service="nanobanana",
            current_ratio=current_ratio,
            num_refs=len(reference_images),
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_banana_pro")
async def handle_model_banana_pro(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Banana Pro"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")
    reference_images = data.get("reference_images", [])
    ref_text = (
        f"📎 Референсов: <code>{len(reference_images)}</code>"
        if reference_images
        else ""
    )

    await state.update_data(img_service="banana_pro")

    text = (
        f"🖼 <b>Создание фото</b>"
        f"{ref_text}"
        f"✨ Модель: <code>banana_pro</code>\n"
        f"📐 Формат: <code>{current_ratio}</code>"
        f"<b>Введите промпт для генерации:</b>"
        f"Опишите что хотите создать:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_create_image_keyboard(
            current_service="banana_pro",
            current_ratio=current_ratio,
            num_refs=len(reference_images),
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_seedream")
async def handle_model_seedream(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Seedream 5.0 (Novita)"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")
    reference_images = data.get("reference_images", [])
    ref_text = (
        f"📎 Референсов: <code>{len(reference_images)}</code>"
        if reference_images
        else ""
    )

    await state.update_data(img_service="seedream")

    text = (
        f"🖼 <b>Создание фото</b>"
        f"{ref_text}"
        f"✨ Модель: <code>seedream</code>\n"
        f"📐 Формат: <code>{current_ratio}</code>"
        f"<b>Введите промпт для генерации:</b>"
        f"Опишите что хотите создать:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_create_image_keyboard(
            current_service="seedream",
            current_ratio=current_ratio,
            num_refs=len(reference_images),
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_seedream_45")
async def handle_model_seedream_45(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Seedream 4.5 (Novita)"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")
    reference_images = data.get("reference_images", [])
    ref_text = (
        f"📎 Референсов: <code>{len(reference_images)}</code>"
        if reference_images
        else ""
    )

    await state.update_data(img_service="seedream_45")

    text = (
        f"🖼 <b>Создание фото</b>"
        f"{ref_text}"
        f"✨ Модель: <code>seedream_45</code>\n"
        f"📐 Формат: <code>{current_ratio}</code>"
        f"<b>Введите промпт для генерации:</b>"
        f"Опишите что хотите создать:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_create_image_keyboard(
            current_service="seedream_45",
            current_ratio=current_ratio,
            num_refs=len(reference_images),
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_z_image_turbo_lora")
async def handle_model_z_image_turbo_lora(
    callback: types.CallbackQuery, state: FSMContext
):
    """Выбор модели Z-Image Turbo LoRA"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")
    reference_images = data.get("reference_images", [])
    ref_text = (
        f"📎 Референсов: <code>{len(reference_images)}</code>"
        if reference_images
        else ""
    )

    await state.update_data(img_service="z_image_turbo_lora")

    text = (
        f"🖼 <b>Создание фото</b>"
        f"{ref_text}"
        f"✨ Модель: <code>z_image_turbo_lora</code>\n"
        f"📐 Формат: <code>{current_ratio}</code>"
        f"<b>Введите промпт для генерации:</b>"
        f"Опишите что хотите создать:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_create_image_keyboard(
            current_service="z_image_turbo_lora",
            current_ratio=current_ratio,
            num_refs=len(reference_images),
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_banana_2")
async def handle_model_banana_2(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Banana 2 (Gemini 3.1 Flash Image Preview)"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")

    await state.update_data(img_service="banana_2")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service="banana_2",
            current_ratio=current_ratio,
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_seedream_5_lite")
async def handle_model_seedream_5_lite(
    callback: types.CallbackQuery, state: FSMContext
):
    """Выбор модели Seedream 5.0 Lite Image-to-Image"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")

    await state.update_data(img_service="seedream_5_lite")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service="seedream_5_lite",
            current_ratio=current_ratio,
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "model_seedream_edit")
async def handle_model_seedream_edit(callback: types.CallbackQuery, state: FSMContext):
    """Выбор модели Seedream 4.5"""
    data = await state.get_data()
    current_ratio = data.get("img_ratio", "1:1")

    await state.update_data(img_service="seedream_edit")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service="seedream_edit",
            current_ratio=current_ratio,
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


# Обработчики формата изображения
@router.callback_query(F.data == "img_ratio_1_1")
async def handle_img_ratio_1_1(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 1:1"""
    data = await state.get_data()
    current_service = data.get("img_service", "banana_pro")

    await state.update_data(img_ratio="1:1")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service=current_service,
            current_ratio="1:1",
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "img_ratio_16_9")
async def handle_img_ratio_16_9(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 16:9"""
    data = await state.get_data()
    current_service = data.get("img_service", "banana_pro")

    await state.update_data(img_ratio="16:9")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service=current_service,
            current_ratio="16:9",
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "img_ratio_9_16")
async def handle_img_ratio_9_16(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 9:16"""
    data = await state.get_data()
    current_service = data.get("img_service", "banana_pro")

    await state.update_data(img_ratio="9:16")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service=current_service,
            current_ratio="9:16",
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "img_ratio_4_3")
async def handle_img_ratio_4_3(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 4:3"""
    data = await state.get_data()
    current_service = data.get("img_service", "banana_pro")

    await state.update_data(img_ratio="4:3")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service=current_service,
            current_ratio="4:3",
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "img_ratio_3_2")
async def handle_img_ratio_3_2(callback: types.CallbackQuery, state: FSMContext):
    """Выбор формата изображения 3:2"""
    data = await state.get_data()
    current_service = data.get("img_service", "banana_pro")

    await state.update_data(img_ratio="3:2")

    await callback.message.edit_reply_markup(
        reply_markup=get_create_image_keyboard(
            current_service=current_service,
            current_ratio="3:2",
        )
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


# =============================================================================
# СЛУЖЕБНЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С ФАЙЛАМИ
# =============================================================================


def save_uploaded_file(file_bytes: bytes, file_ext: str = "png", *, is_reference: bool = False, category: str | None = None) -> Optional[str]:
    """
    Сохраняет загруженный файл в папку static/uploads и возвращает публичный URL.
    """
    try:
        # Создаём поддиректорию по policy: uploads/<category>/<date>/file
        date_str = datetime.now().strftime("%Y%m%d")
        category = category or choose_upload_category(file_ext, is_reference=is_reference)

        # Генерируем уникальное имя файла
        file_id = str(uuid.uuid4())[:8]
        filename = f"{file_id}.{file_ext}"
        filepath = upload_path(os.path.join("static", "uploads"), category, date_str, filename)
        os.makedirs(filepath.parent, exist_ok=True)

        # Сохраняем файл
        with open(filepath, "wb") as f:
            f.write(file_bytes)

        # Формируем публичный URL
        # nginx настроен на /uploads/ -> static/uploads/
        base_url = config.static_base_url
        public_url = public_upload_url(base_url, category, date_str, filename)

        logger.info(f"Saved uploaded file: {public_url}")
        return public_url

    except Exception as e:
        logger.exception(f"Error saving uploaded file: {e}")
        return None


def _serialize_reference_images(reference_images: list) -> Optional[str]:
    refs = [str(url) for url in (reference_images or []) if url]
    return json.dumps(refs, ensure_ascii=False) if refs else None


def _deserialize_reference_images(raw_refs: Optional[str]) -> list:
    if not raw_refs:
        return []
    try:
        refs = json.loads(raw_refs)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(refs, list):
        return []
    return [str(url) for url in refs if url]


def _extract_reference_images_from_message(message: Optional[types.Message]) -> list:
    if not message:
        return []

    candidates = []
    try:
        candidates.append(message.html_text)
    except Exception:
        pass
    try:
        candidates.append(message.html_caption)
    except Exception:
        pass
    candidates.extend(
        [getattr(message, "caption", None), getattr(message, "text", None)]
    )

    for text in candidates:
        if not text or "Исходники" not in text:
            continue
        block = text.split("Исходники", 1)[1]
        block = block.split("🔗", 1)[0]
        refs = re.findall(r"<a\s+href=['\"]([^'\"]+)['\"]", block)
        if not refs:
            refs = re.findall(r"https?://[^\s<>'\"]+", block)
        if refs:
            return refs[:14]
    return []


async def _send_original_document(
    send_callable,
    result: bytes,
    saved_url: Optional[str],
    filename: str = "original.png",
):
    """Helper to send original document with fallbacks and logging.

    send_callable: coroutine function like message.answer_document
    """
    try:
        logger.info("Sending original document via BufferedInputFile")
        doc = types.BufferedInputFile(result, filename=filename)
        await send_callable(
            document=doc, caption="📥 Исходный файл (оригинал)", parse_mode="HTML"
        )
        logger.info("Original document sent (BufferedInputFile)")
        return
    except Exception:
        logger.exception(
            "Failed to send original document via BufferedInputFile, trying fallback"
        )

    try:
        if saved_url:
            logger.info("Sending original document via saved URL")
            await send_callable(
                document=saved_url,
                caption="📥 Исходный файл (оригинал)",
                parse_mode="HTML",
            )
            logger.info("Original document sent via URL")
            return

        bio = io.BytesIO(result)
        bio.name = filename
        bio.seek(0)
        logger.info("Sending original document via BytesIO fallback")
        await send_callable(
            document=bio, caption="📥 Исходный файл (оригинал)", parse_mode="HTML"
        )
        logger.info("Original document sent via BytesIO")
    except Exception:
        logger.exception("Fallback to send original document failed")


async def _send_download_link(send_callable, saved_url: str):
    """Send a small message with an inline URL button to download the original file."""
    try:
        kb = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="📥 Скачать оригинал", url=saved_url)]
            ]
        )
        await send_callable(
            f"📥 <b>Исходник</b> — можно скачать по ссылке:",
            reply_markup=kb,
            parse_mode="HTML",
        )
        logger.info("Sent download link to user")
    except Exception:
        logger.exception("Failed to send download link")


# =============================================================================
# ОСНОВНЫЕ ОБРАБОТЧИКИ БЕЗ ПРЕСЕТОВ
# =============================================================================


@router.callback_query(F.data == "generate_image")
async def start_image_generation(callback: types.CallbackQuery, state: FSMContext):
    """Начинает генерацию изображения - Шаг 1: загрузка референсов"""
    user_credits = await get_user_credits(callback.from_user.id)
    settings = await get_user_settings(callback.from_user.id)
    image_service = resolve_image_model(settings.get("image_service", "banana_pro"))
    image_options = normalize_image_options(image_service)

    # Инициализируем опции
    await state.set_state(GenerationStates.waiting_for_image)
    await state.update_data(
        generation_type="image",
        image_service=image_service,
        reference_images=[],
        generation_options={
            "model": image_service,
            "aspect_ratio": image_options["aspect_ratio"],
            "quality": "pro",
        },
        img_service=image_service,
        img_ratio=image_options["aspect_ratio"],
        img_options=image_options,
    )

    model_config = get_image_model_config(image_service)
    model_name = model_config["label"]
    model_cost = str(preset_manager.get_generation_cost(model_config["cost_key"]))

    # Шаг 1: Загрузка референсов
    await callback.message.edit_text(
        f"🖼 <b>Генерация фото</b>"
        f"🪙 Ваш баланс: <code>{user_credits}</code> BoomCoin\n"
        f"🤖 Модель: {model_name} ({model_cost}🪙)"
        f"<b>Шаг 1: Референсы (опционально)</b>"
        f"Загрузите изображения для:\n"
        f"• Точного сходства с объектом\n"
        f"• Сохранения стиля\n"
        f"• Персонажей (до 4 фото)"
        f"После загрузки нажмите ▶️ Продолжить\n"
        f"Или ⏭ Пропустить, если референсы не нужны",
        reply_markup=get_reference_images_upload_keyboard(0, 14, "generate_image"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "edit_image")
async def start_image_editing(callback: types.CallbackQuery, state: FSMContext):
    """Начинает редактирование изображения с возможностью сохранения лиц через референсы"""
    await state.set_state(GenerationStates.waiting_for_image)

    user_credits = await get_user_credits(callback.from_user.id)

    # Сохраняем модель и тип генерации в state + инициализируем референсы
    await state.update_data(
        generation_type="image_edit",
        preferred_model="pro",  # Для редактирования используем Pro для лучшего качества
        reference_images=[],  # Для сохранения лиц
    )

    # Получаем стоимость редактирования через preset_manager
    edit_cost = preset_manager.get_generation_cost("gemini-3-pro-image-preview")

    await callback.message.edit_text(
        f"✏️ <b>Редактирование фото</b>"
        f"🪙 Ваш баланс: <code>{user_credits}</code> BoomCoin\n"
        f"🤖 Модель: 💎 Banano Pro ({edit_cost}🪙, 4K, сохранение лиц)"
        f"<b>Как редактировать:</b>\n"
        f"1. Загрузите <b>главное фото</b> для редактирования\n"
        f"2. Добавьте до <b>4 фото лица</b> для сохранения (опционально)\n"
        f"3. Опишите что изменить"
        f"<i>💡 Для сохранения лица: загрузите сначала главное фото,\n"
        f"потом фото лица для сохранения, затем введите промпт</i>",
        reply_markup=get_back_keyboard("back_main"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "generate_video")
async def start_video_generation(callback: types.CallbackQuery, state: FSMContext):
    """Начинает генерацию видео без пресета - сразу запрашивает промпт"""
    await state.set_state(GenerationStates.waiting_for_input)
    await state.update_data(generation_type="video")

    user_credits = await get_user_credits(callback.from_user.id)
    settings = await get_user_settings(callback.from_user.id)
    video_model = settings["preferred_video_model"]

    # Map model codes to names
    model_names = {
        "v3_std": "⚡ Standard",
        "v3_pro": "💎 Pro",
        "v3_omni_std": "🌀 Omni Std",
        "v3_omni_pro": "🌀 Omni Pro",
    }
    # Используем preset_manager для получения стоимости
    model_cost = str(preset_manager.get_video_cost(video_model, 5))
    model_name = model_names.get(video_model, video_model)

    # Простые опции видео
    video_options = {
        "duration": 5,
        "aspect_ratio": "16:9",
        "quality": "std",
        "generate_audio": True,
    }
    await state.update_data(video_options=video_options)

    await callback.message.edit_text(
        f"🎬 <b>Генерация видео</b>"
        f"🪙 Ваш баланс: <code>{user_credits}</code> BoomCoin\n"
        f"🤖 Модель: {model_name} ({model_cost}🪙)"
        f"<b>Опции видео:</b>\n"
        f"   ⏱ Длительность: <code>{video_options.get('duration', 5)} сек</code>\n"
        f"   📐 Формат: <code>{video_options.get('aspect_ratio', '16:9')}</code>\n"
        f"   🔊 Со звуком: <code>{'Да' if video_options.get('generate_audio') else 'Нет'}</code>"
        f"Опишите видео, которое хотите создать:\n"
        f"• Что происходит в сцене\n"
        f"• Движение камеры\n"
        f"• Стиль и атмосфера"
        f"<i>Чем подробнее описание — тем лучше результат!</i>",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="⚙️ Изменить опции", callback_data="video_options_change"
                    )
                ],
                [types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")],
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "video_options_change")
async def handle_video_options_change(callback: types.CallbackQuery, state: FSMContext):
    """Показывает клавиатуру опций видео (длительность, формат, звук)"""
    data = await state.get_data()
    video_options = data.get(
        "video_options",
        {
            "duration": 5,
            "aspect_ratio": "16:9",
            "quality": "std",
            "generate_audio": True,
        },
    )

    user_prompt = data.get("user_prompt", "")

    # Если промпт ещё не введён, показываем дефолтный текст
    prompt_text = user_prompt if user_prompt else "<i>Опишите видео ниже</i>"

    await callback.message.edit_text(
        f"🎬 <b>Настройка видео</b>"
        f"Промпт: <code>{prompt_text[:100]}{'...' if len(prompt_text) > 100 else ''}</code>"
        f"Выберите параметры и нажмите ▶️ Запустить:"
        f"<i>⏱ Длительность: {video_options.get('duration', 5)} сек\n"
        f"📐 Формат: {video_options.get('aspect_ratio', '16:9')}\n"
        f"🔊 Звук: {'Да' if video_options.get('generate_audio') else 'Нет'}</i>",
        reply_markup=get_video_options_no_preset_keyboard(
            video_options.get("duration", 5),
            video_options.get("aspect_ratio", "16:9"),
            video_options.get("generate_audio", True),
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "edit_video")
async def start_video_editing(callback: types.CallbackQuery, state: FSMContext):
    """Начинает редактирование видео - предлагает выбрать тип входных данных"""
    await state.clear()

    user_credits = await get_user_credits(callback.from_user.id)
    settings = await get_user_settings(callback.from_user.id)
    video_model = settings["preferred_i2v_model"]

    # Map model codes to names
    model_names = {
        "v3_std": "⚡ Standard",
        "v3_pro": "💎 Pro",
        "v3_omni_std": "🌀 Omni Std",
        "v3_omni_pro": "🌀 Omni Pro",
    }
    # Используем preset_manager для получения стоимости
    model_cost = str(preset_manager.get_video_cost(video_model, 5))
    model_name = model_names.get(video_model, video_model)

    # Инициализируем опции для видео-эффектов
    video_edit_options = {
        "quality": "std",  # std или pro
        "duration": 5,
        "aspect_ratio": "16:9",
    }
    await state.update_data(video_edit_options=video_edit_options)

    from bot.keyboards import get_video_edit_input_type_keyboard

    await callback.message.edit_text(
        f"✂️ <b>Видео-эффекты</b>"
        f"🪙 Ваш баланс: <code>{user_credits}</code> BoomCoin\n"
        f"🤖 Модель: {model_name} ({model_cost}🪙)"
        f"<b>Kling 3 Omni</b>\n"
        f"Выберите, что хотите загрузить:"
        f"🎬 <b>Видео</b> - преобразование видео\n"
        f"🖼 <b>Фото</b> - создание видео из изображения"
        f"<i>Загрузите медиафайл и опишите эффект</i>",
        reply_markup=get_video_edit_input_type_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "image_to_video")
async def start_image_to_video(callback: types.CallbackQuery, state: FSMContext):
    """Начинает генерацию видео из фото - запрашивает фото"""
    await state.set_state(GenerationStates.waiting_for_image)
    await state.update_data(generation_type="image_to_video")

    user_credits = await get_user_credits(callback.from_user.id)
    settings = await get_user_settings(callback.from_user.id)
    video_model = settings["preferred_i2v_model"]

    # Map model codes to names
    model_names = {
        "v3_std": "⚡ Standard",
        "v3_pro": "💎 Pro",
        "v3_omni_std": "🌀 Omni Std",
        "v3_omni_pro": "🌀 Omni Pro",
    }
    # Используем preset_manager для получения стоимости
    model_cost = str(preset_manager.get_video_cost(video_model, 5))
    model_name = model_names.get(video_model, video_model)

    # Простые опции видео
    video_options = {
        "duration": 5,
        "aspect_ratio": "16:9",
        "quality": "std",
        "generate_audio": True,
    }
    await state.update_data(video_options=video_options)

    await callback.message.edit_text(
        f"🖼 <b>Фото в видео</b>"
        f"🪙 Ваш баланс: <code>{user_credits}</code> BoomCoin\n"
        f"🤖 Модель: {model_name} ({model_cost}🪙)"
        f"<b>Kling 3 - Image to Video</b>\n"
        f"Загрузите изображение,\n"
        f"которое хотите превратить в видео.\n"
        f"После загрузки опишите движение."
        f"<i>Например: птица летит в небе, волны накатывают на берег</i>",
        reply_markup=get_back_keyboard("back_main"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


# =============================================================================
# ОБРАБОТЧИКИ ОПЦИЙ ВИДЕО-ЭФФЕКТОВ
# =============================================================================


@router.callback_query(F.data.startswith("video_edit_input_"))
async def handle_video_edit_input_type(
    callback: types.CallbackQuery, state: FSMContext
):
    """Выбор типа входного медиа для видео-эффектов: видео или изображение"""
    choice = callback.data.replace("video_edit_input_", "")

    if choice == "video":
        await state.set_state(GenerationStates.waiting_for_video)
        await state.update_data(
            generation_type="video_edit",
            video_edit_input_type="video",
            has_video=False,
            has_image=False,
        )
        text = (
            "✂️ <b>Видео-эффекты</b>"
            "<b>Режим: Преобразование видео</b>"
            "Загрузите видео (3-10 секунд), которое хотите преобразить.\n"
            "После загрузки опишите желаем эффект."
        )
    else:
        await state.set_state(GenerationStates.waiting_for_image)
        await state.update_data(
            generation_type="video_edit_image",
            video_edit_input_type="image",
            has_video=False,
            has_image=False,
        )
        text = (
            "✂️ <b>Видео-эффекты</b>"
            "<b>Режим: Создание видео из фото</b>"
            "Загрузите изображение, которое хотите превратить в видео.\n"
            "После загрузки опишите движение и эффект."
        )

    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard("edit_video"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data == "video_edit_change_type")
async def handle_video_edit_change_type(
    callback: types.CallbackQuery, state: FSMContext
):
    """Сброс и выбор нового типа входного медиа для видео-эффектов"""
    video_edit_options = {"quality": "std", "duration": 5, "aspect_ratio": "16:9"}
    await state.update_data(video_edit_options=video_edit_options)

    from bot.keyboards import get_video_edit_input_type_keyboard

    user_credits = await get_user_credits(callback.from_user.id)

    await callback.message.edit_text(
        f"✂️ <b>Видео-эффекты</b>"
        f"🪙 Ваш баланс: <code>{user_credits}</code> BoomCoin"
        f"<b>Kling 3 Omni</b>\n"
        f"Выберите, что хотите загрузить:"
        f"🎬 <b>Видео</b> - преобразование видео\n"
        f"🖼 <b>Фото</b> - создание видео из изображения"
        f"<i>Загрузите медиафайл и опишите эффект</i>",
        reply_markup=get_video_edit_input_type_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("video_edit_quality_"))
async def handle_video_edit_quality(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора качества для видео-эффектов"""
    quality = callback.data.replace("video_edit_quality_", "")

    data = await state.get_data()
    video_edit_options = data.get("video_edit_options", {})
    video_edit_options["quality"] = quality
    await state.update_data(video_edit_options=video_edit_options)

    await show_video_edit_options(callback, state, quality, video_edit_options)
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("video_edit_duration_"))
async def handle_video_edit_duration(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора длительности для видео-эффектов"""
    duration = int(callback.data.replace("video_edit_duration_", ""))

    data = await state.get_data()
    video_edit_options = data.get("video_edit_options", {})
    video_edit_options["duration"] = duration
    await state.update_data(video_edit_options=video_edit_options)

    await show_video_edit_options(
        callback, state, video_edit_options.get("quality", "std"), video_edit_options
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("video_edit_ratio_"))
async def handle_video_edit_ratio(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора формата для видео-эффектов"""
    # Формат: video_edit_ratio_9_16 -> 9:16
    ratio_part = callback.data.replace("video_edit_ratio_", "")
    aspect_ratio = ratio_part.replace("_", ":")

    data = await state.get_data()
    video_edit_options = data.get("video_edit_options", {})
    video_edit_options["aspect_ratio"] = aspect_ratio
    await state.update_data(video_edit_options=video_edit_options)

    await show_video_edit_options(
        callback, state, video_edit_options.get("quality", "std"), video_edit_options
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


async def show_video_edit_options(
    callback: types.CallbackQuery, state: FSMContext, quality: str, options: dict
):
    data = await state.get_data()
    input_type = data.get("video_edit_input_type", "video")
    has_video = data.get("has_video", False)
    has_image = data.get("has_image", False)
    user_prompt = data.get("video_edit_prompt", "")

    quality_emoji = "💎" if quality == "pro" else "⚡"

    if input_type == "video":
        media_status = "✅ Загружено" if has_video else "⏳ Ожидание загрузки"
        media_text = "🎬 Видео"
    else:
        media_status = "✅ Загружено" if has_image else "⏳ Ожидание загрузки"
        media_text = "🖼 Изображение"

    text = f"✂️ <b>Видео-эффекты</b>"
    text += f"<b>Опции:</b>\n"
    text += f"   {quality_emoji} Качество: <code>{quality.upper()}</code>\n"
    text += f"   ⏱ Длительность: <code>{options.get('duration', 5)} сек</code>\n"
    text += f"   📐 Формат: <code>{options.get('aspect_ratio', '16:9')}</code>"
    text += f"{media_text}: {media_status}\n"
    if user_prompt:
        text += f"📝 Промпт: <code>{user_prompt[:50]}...</code>\n"
    text += f"\n<i>Загрузите {'видео' if input_type == 'video' else 'фото'} и опишите эффект</i>"

    await callback.message.edit_text(
        text,
        reply_markup=get_video_edit_keyboard(
            input_type=input_type,
            quality=quality,
            duration=options.get("duration", 5),
            aspect_ratio=options.get("aspect_ratio", "16:9"),
        ),
        parse_mode="HTML",
    )


# =============================================================================
# ОБРАБОТЧИКИ ПРЕСЕТОВ (ЕСЛИ НУЖНО ВЕРНУТЬ)
# =============================================================================


# =============================================================================
# ОБРАБОТЧИКИ ОПЦИЙ ГЕНЕРАЦИИ (НОВОЕ СОГЛАСНО banana_api.md)
# =============================================================================


@router.callback_query(F.data.startswith("model_"))
async def handle_model_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора модели генерации"""
    parts = callback.data.split("_")
    if len(parts) >= 3:
        preset_id = parts[1]
        model_type = parts[2]  # "flash" или "pro"

        model = (
            "gemini-2.5-flash-image"
            if model_type == "flash"
            else "gemini-3-pro-image-preview"
        )

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["model"] = model
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            model_emoji = "💎" if "pro" in model else "⚡"
            text = f"✅ <b>Модель изменена</b>"
            text += f"{model_emoji} Теперь используется: <code>{model}</code>"

            if model_type == "flash":
                text += "<i>Быстрая генерация, до 1024px</i>\n"
            else:
                text += "<i>Высокое качество, до 4K, с thinking</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("resolution_"))
async def handle_resolution_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора разрешения изображения"""
    parts = callback.data.split("_")
    if len(parts) >= 3:
        preset_id = parts[1]
        resolution = parts[2]  # "1K", "2K", "4K"

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["resolution"] = resolution
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            res_emoji = {"1K": "⚡", "2K": "💎", "4K": "👑"}.get(resolution, "⚡")
            text = f"✅ <b>Разрешение изменено</b>"
            text += f"{res_emoji} Теперь используется: <code>{resolution}</code>"

            resolutions = {
                "1K": "Стандартное качество, 1024px",
                "2K": "HD качество, 2048px",
                "4K": "Максимальное качество, 4096px",
            }
            text += f"<i>{resolutions.get(resolution, '')}</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(
    F.data.startswith("img_ratio_") & ~F.data.startswith("img_ratio_no_preset")
)
async def handle_image_ratio_selection(
    callback: types.CallbackQuery, state: FSMContext
):
    """Обработка выбора формата изображения для пресетов"""
    parts = callback.data.split("_")
    if len(parts) >= 4:
        preset_id = parts[1]
        ratio = f"{parts[2]}:{parts[3]}"  # "16:9"

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["aspect_ratio"] = ratio
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            text = f"✅ <b>Формат изменён</b>"
            text += f"📐 Теперь используется: <code>{ratio}</code>"

            ratios_desc = {
                "1:1": "Квадрат (Instagram, Facebook)",
                "16:9": "Горизонтальный (YouTube)",
                "9:16": "Вертикальный (TikTok, Reels)",
                "4:5": "Портретный (Instagram)",
                "21:9": "Панорамный (Кино)",
            }
            text += f"<i>{ratios_desc.get(ratio, '')}</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("grounding_"))
async def handle_search_grounding(callback: types.CallbackQuery, state: FSMContext):
    """Обработка поискового заземления (Grounding)"""
    parts = callback.data.split("_")
    if len(parts) >= 2:
        preset_id = parts[1]

        # Переключаем опцию
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["enable_search"] = not generation_options.get(
            "enable_search", False
        )
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            enabled = generation_options["enable_search"]
            status = "🟢 ВКЛ" if enabled else "🔴 ВЫКЛ"
            text = f"✅ <b>Поиск в интернете: {status}</b>"

            if enabled:
                text += "<i>AI будет использовать Google Search для актуальной информации</i>\n"
                text += "\nПримеры:\n"
                text += "• Погода на 5 дней\n"
                text += "• Последние новости\n"
                text += "• Актуальные события"
            else:
                text += "<i>Поиск отключён</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("ref_"))
async def handle_reference_images(callback: types.CallbackQuery, state: FSMContext):
    """
    Обработка работы с референсными изображениями (до 14 шт)
    Поддерживает загрузку, управление и подтверждение референсов
    """
    parts = callback.data.split("_")
    action = parts[1] if len(parts) > 1 else ""
    preset_id = parts[2] if len(parts) > 2 else None

    data = await state.get_data()
    current_refs = data.get("reference_images", [])
    max_refs = 14

    if action == "upload":
        # Начинаем загрузку референсных изображений
        await state.set_state(GenerationStates.uploading_reference_images)
        await state.update_data(preset_id=preset_id, reference_images=current_refs)

        await callback.message.edit_text(
            f"📎 <b>Загрузка референсных изображений</b>"
            f"Загружено: <code>{len(current_refs)}/{max_refs}</code>"
            f"Отправьте фотографии (до {max_refs} штук), которые будут использоваться как референсы:\n"
            f"• До 10 объектов с высокой точностью\n"
            f"• До 4 персонажей для консистентности\n"
            f"• До 14 изображений суммарно"
            f"После загрузки нажмите ▶️ Продолжить",
            reply_markup=get_reference_images_upload_keyboard(
                len(current_refs), max_refs, preset_id
            ),
            parse_mode="HTML",
        )

    elif action == "clear":
        # Очищаем все референсы
        await state.update_data(reference_images=[])
        await callback.message.edit_text(
            f"📎 <b>Референсы очищены</b>"
            f"Загружено: <code>0/{max_refs}</code>"
            f"Отправьте фотографии для загрузки референсов:",
            reply_markup=get_reference_images_upload_keyboard(0, max_refs, preset_id),
            parse_mode="HTML",
        )

    elif action == "confirm":
        # Переходим к подтверждению
        if not current_refs:
            await callback.answer("❌ Нет загруженных изображений", show_alert=True)
            return

        # Для нового UX (preset_id == "new") - сразу переходим к выбору модели
        # (пропускаем экран подтверждения референсов)
        if preset_id == "new":
            data = await state.get_data()
            current_service = data.get("img_service", "banana_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>"
                f"Введите промпт для генерации:",
                reply_markup=get_create_image_keyboard(
                    current_service, current_ratio, num_refs=len(current_refs)
                ),
                parse_mode="HTML",
            )
            await callback.answer()
            await state.set_state(GenerationStates.waiting_for_input)
        else:
            # Для пресетов - сразу переходим к экрану пресета (пропускаем экран подтверждения)
            preset = preset_manager.get_preset(preset_id)
            if preset:
                await show_preset_details(
                    callback.message, preset, callback.from_user.id
                )
            else:
                # Fallback - показать параметры генерации
                data = await state.get_data()
                current_service = data.get("img_service", "banana_pro")
                current_ratio = data.get("img_ratio", "1:1")
                await callback.message.edit_text(
                    f"✨ <b>Создание фото</b>"
                    f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                    f"✨ Модель: <code>{current_service}</code>\n"
                    f"📐 Формат: <code>{current_ratio}</code>"
                    f"Введите промпт для генерации:",
                    reply_markup=get_create_image_keyboard(
                        current_service, current_ratio
                    ),
                    parse_mode="HTML",
                )
                await state.set_state(GenerationStates.waiting_for_input)

    elif action == "reload":
        # Перезагружаем — очищаем и начинаем заново
        await state.update_data(reference_images=[])
        await state.set_state(GenerationStates.uploading_reference_images)

        await callback.message.edit_text(
            f"📎 <b>Перезагрузка референсов</b>"
            f"Загружено: <code>0/{max_refs}</code>"
            f"Отправьте новые фотографии для загрузки референсов:",
            reply_markup=get_reference_images_upload_keyboard(0, max_refs, preset_id),
            parse_mode="HTML",
        )

    elif action == "accept":
        # Сохраняем референсы в generation_options
        generation_options = data.get("generation_options", {})
        generation_options["reference_images"] = current_refs
        await state.update_data(generation_options=generation_options)

        # Для нового UX (preset_id == "new") - переходим к экрану выбора модели/формата
        # (пропускаем промежуточное меню подтверждения)
        if preset_id == "new":
            current_service = data.get("img_service", "banana_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>"
                f"Введите промпт для генерации:",
                reply_markup=get_create_image_keyboard(current_service, current_ratio),
                parse_mode="HTML",
            )
            await state.set_state(GenerationStates.waiting_for_input)
        else:
            # Для пресетов - возвращаемся к экрану пресета
            preset = preset_manager.get_preset(preset_id)
            if preset:
                await show_preset_details(
                    callback.message, preset, callback.from_user.id
                )
            else:
                # Этот код не должен достигаться в нормальном потоке, но оставим для совместимости
                await callback.message.edit_text(
                    "✅ Референсы сохранены!",
                    reply_markup=get_back_keyboard("back_main"),
                )

    else:
        # Показываем справку о референсах (стандартное поведение)
        help_text = get_reference_images_help()

        await callback.message.edit_text(
            help_text,
            reply_markup=get_reference_images_keyboard(preset_id),
            parse_mode="HTML",
        )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


# =============================================================================
# ОБРАБОТЧИКИ ВВОДА ПОЛЬЗОВАТЕЛЯ
# =============================================================================


@router.callback_query(F.data.startswith("custom_"))
async def request_custom_input(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает пользовательский ввод для пресета"""
    preset_id = callback.data.replace("custom_", "")
    preset = preset_manager.get_preset(preset_id)

    if not preset:
        await callback.answer("Пресет не найден")
        return

    await state.update_data(preset_id=preset_id, input_type="custom")

    # Если требуется загрузка файла
    if preset.requires_upload:
        await state.set_state(GenerationStates.waiting_for_image)

        hint = UserHints.get_hint_for_stage("input")
        await callback.message.edit_text(
            (
                "📎 <b>Загрузите изображение</b>\n\n"
                f"Пресет: <b>{preset.name}</b>\n"
                f"После загрузки изображения {preset.input_prompt or 'введите описание'}\n\n"
                f"<i>{hint}</i>"
            ),
            reply_markup=get_back_keyboard(f"preset_{preset_id}"),
            parse_mode="HTML",
        )
    else:
        await state.set_state(GenerationStates.waiting_for_input)

        hint = UserHints.get_hint_for_stage("input")
        await callback.message.edit_text(
            (
                "✏️ <b>Введите ваш вариант</b>\n\n"
                f"{preset.input_prompt or 'Опишите, что хотите создать'}\n\n"
                "Примеры для вдохновения:\n"
                "• Стиль: минимализм, винтаж, футуризм\n"
                "• Цветовая схема: яркий, пастельный, тёмный\n"
                "• Эмоция: радостное, удивлённое, задумчивое\n\n"
                f"<i>{hint}</i>"
            ),
            reply_markup=get_back_keyboard(f"preset_{preset_id}"),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("default_"))
async def use_default_values(callback: types.CallbackQuery, state: FSMContext):
    """Использует пример значений для пресета"""
    preset_id = callback.data.replace("default_", "")
    preset = preset_manager.get_preset(preset_id)

    if not preset:
        await callback.answer("Пресет не найден")
        return

    # Заполняем плейсхолдеры значениями по умолчанию
    defaults = preset_manager.get_default_values("styles") or ["минимализм"]
    color_defaults = preset_manager.get_default_values("color_schemes") or ["яркий"]
    expr_defaults = preset_manager.get_default_values("expressions") or ["радостное"]

    placeholder_values = {}
    for placeholder in preset.placeholders:
        if "style" in placeholder.lower():
            placeholder_values[placeholder] = defaults[0]
        elif "color" in placeholder.lower():
            placeholder_values[placeholder] = color_defaults[0]
        elif "expr" in placeholder.lower():
            placeholder_values[placeholder] = expr_defaults[0]
        else:
            placeholder_values[placeholder] = "пример"

    try:
        final_prompt = preset.format_prompt(**placeholder_values)
    except:
        final_prompt = preset.prompt.replace("{", "").replace("}", "")

    await state.update_data(
        preset_id=preset_id, final_prompt=final_prompt, input_type="default"
    )

    # Показываем финальный промпт с подтверждением
    data = await state.get_data()
    generation_options = data.get("generation_options", {})

    await callback.message.edit_text(
        (
            "▶️ <b>Подтвердите генерацию</b>\n\n"
            f"Пресет: <b>{preset.name}</b>\n"
            f"Стоимость: <code>{preset.cost}</code>🪙\n\n"
            "<b>Промпт:</b>\n"
            f"<code>{final_prompt[:300]}{'...' if len(final_prompt) > 300 else ''}</code>"
            f"{format_generation_options(generation_options)}"
        ),
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="✅ Запустить", callback_data=f"run_{preset_id}"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="❌ Отмена", callback_data=f"preset_{preset_id}"
                    )
                ],
            ]
        ),
        parse_mode="HTML",
    )


@router.message(GenerationStates.waiting_for_video_prompt, F.photo)
async def process_photo_for_video_prompt_state(
    message: types.Message, state: FSMContext
):
    """
    Обрабатывает фото для imgtxt видео в состоянии waiting_for_video_prompt.
    Первое фото - v_image_url (старт кадр), остальные - reference_images.
    """
    data = await state.get_data()
    v_type = data.get("v_type")
    v_model = data.get("v_model")
    if v_type == "video" and v_model == "happyhorse_edit":
        reference_images = data.get("reference_images", [])
        if len(reference_images) >= 5:
            await message.answer(
                "❌ Для HappyHorse Edit можно добавить до 5 фото-референсов. Введите промпт."
            )
            return
    elif v_type != "imgtxt" and v_model != "gemini_omni":
        await message.answer("Пожалуйста, отправьте текстовое описание.")
        return

    # Download photo
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    image_bytes = await message.bot.download_file(file.file_path)
    image_data = image_bytes.read()

    # Validate
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(image_data))
        width, height = img.size
        logger.info(f"Image validated for Kling: {width}×{height}")
        if width < 300 or height < 300:
            await message.answer(
                f"❌ Изображение слишком маленькое: {width}×{height} (мин 300px)"
            )
            return
    except Exception as e:
        logger.error(f"Image validation failed: {e}")
        await message.answer("❌ Не удалось обработать изображение.")
        return

    image_url = save_uploaded_file(image_data, "png", is_reference=True)
    if not image_url:
        await message.answer("❌ Не удалось сохранить фото.")
        return

    v_image_url = data.get("v_image_url")
    reference_images = data.get("reference_images", [])

    if v_type == "video" and v_model == "happyhorse_edit":
        reference_images.append(image_url)
        await state.update_data(reference_images=reference_images)
        await message.answer(
            f"✅ Фото-референс для HappyHorse Edit добавлен: <code>{len(reference_images)}/5</code>\n\n"
            "Отправьте ещё фото или введите промпт.",
            reply_markup=get_create_video_keyboard(
                current_v_type="video",
                current_model="happyhorse_edit",
                current_duration=data.get("v_duration", 5),
                current_ratio=data.get("v_ratio", "16:9"),
            ),
            parse_mode="HTML",
        )
        return

    start_count = 1 if v_image_url else 0
    current_refs = len(reference_images)
    total = start_count + current_refs + 1  # +1 for this photo
    max_photos = GEMINI_OMNI_MAX_IMAGES if v_model == "gemini_omni" else 9
    if total > max_photos:
        await message.answer(
            f"❌ Максимум {max_photos} фото для этой модели. Введите промпт."
        )
        return

    if not v_image_url:
        # Первое фото - стартовый кадр
        await state.update_data(v_image_url=image_url)
        logger.info(f"Saved start image for video (1st photo): {image_url}")
        status = f"✅ Старт фото установлено! (1/{max_photos})"
    else:
        # Последующие - референсы
        reference_images.append(image_url)
        await state.update_data(reference_images=reference_images)
        logger.info(
            f"Saved reference image for video (ref #{current_refs + 1}): {image_url}"
        )
        status = f"✅ Реф. фото добавлено! (total {total}/{max_photos})"

    # Update UI with current count
    data = await state.get_data()
    current_model = data.get("v_model", "v3_std")
    current_duration = data.get("v_duration", 5)
    current_ratio = data.get("v_ratio", "16:9")

    start_count = 1 if data.get("v_image_url") else 0
    ref_count = len(data.get("reference_images", []))
    total_photos = start_count + ref_count

    text = (
        f"🎬 <b>{'Gemini Omni' if current_model == 'gemini_omni' else 'Фото + Текст → Видео'}</b>\n"
        f"📎 Фото: <code>{total_photos}/{max_photos}</code> (старт + рефы)"
        f"{status}"
        f"⚙️ Модель: <code>{current_model}</code> | {current_duration}с | {current_ratio}\n"
        f"<b>Отправьте ещё фото или промпт:</b>"
    )
    if current_model == "gemini_omni":
        reply_markup = get_gemini_omni_keyboard(
            len(data.get("omni_audio_ids", [])),
            len(data.get("omni_character_ids", [])),
        )
    else:
        reply_markup = get_create_video_keyboard(
            current_v_type="imgtxt",
            current_model=current_model,
            current_duration=current_duration,
            current_ratio=current_ratio,
        )

    await message.answer(
        text,
        reply_markup=reply_markup,
        parse_mode="HTML",
    )


@router.message(
    GenerationStates.uploading_reference_videos,
    F.video | (F.document & F.document.mime_type.startswith("video/")),
)
async def process_reference_video_upload(message: types.Message, state: FSMContext):
    """
    Обрабатывает загрузку нескольких референсных видео для режима video+text.
    """
    data = await state.get_data()
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")
    v_model = data.get("v_model")
    v_reference_videos = data.get("v_reference_videos", [])

    if generation_type == "video" and v_type == "video":
        # Определяем источник файла
        if message.video:
            video_obj = message.video
        elif message.document and message.document.mime_type.startswith("video/"):
            video_obj = message.document
        else:
            await message.answer("❌ Неверный тип файла. Отправьте видео.")
            return

        # Проверяем размер (макс 20MB)
        file_size = getattr(video_obj, "file_size", 0)
        if file_size > 20 * 1024 * 1024:
            await message.answer("❌ Видео слишком большое (макс 20MB).")
            return

        max_refs = 1 if v_model == "gemini_omni" else 5
        if len(v_reference_videos) >= max_refs:
            await message.answer(
                f"❌ Максимум {max_refs} видео референсов. Нажмите 'Продолжить'.",
                parse_mode="HTML",
            )
            return

        file = await message.bot.get_file(video_obj.file_id)
        video_bytes = await message.bot.download_file(file.file_path)
        video_data = video_bytes.read()

        # Сохраняем видео и получаем URL
        video_url = save_uploaded_file(video_data, "mp4", is_reference=True)
        if video_url:
            v_reference_videos.append(video_url)
            await state.update_data(v_reference_videos=v_reference_videos)
            logger.info(f"Added reference video {len(v_reference_videos)}: {video_url}")

            current_count = len(v_reference_videos)
            text = (
                f"📹 <b>Загрузка видео референсов</b>"
                f"Загружено: <code>{current_count}/{max_refs}</code>"
                f"✅ Видео добавлено!"
                f"Отправьте следующее или нажмите кнопку ниже:"
            )
            await message.reply(
                text,
                reply_markup=get_reference_videos_upload_keyboard(
                    current_count, max_refs, "video_new"
                ),
                parse_mode="HTML",
            )
        else:
            await message.answer("❌ Не удалось сохранить видео. Попробуйте ещё раз.")
        return

    await message.answer("Пожалуйста, отправьте видео.")


@router.message(
    GenerationStates.uploading_reference_images,
    F.photo
    | (
        F.document & F.document.mime_type.in_(["image/jpeg", "image/png", "image/webp"])
    ),
)
async def process_reference_photo_upload(message: types.Message, state: FSMContext):
    """Handles reference photo uploads during image creation (up to 14 refs or 9 for video imgtxt)"""
    data = await state.get_data()
    reference_images = data.get("reference_images", [])
    v_type = data.get("v_type")
    max_refs = 14 if data.get("mix_mode") else 9 if v_type == "imgtxt" else 14

    if len(reference_images) >= max_refs:
        await message.answer(
            f"❌ Максимум {max_refs} референсов. Нажмите 'Продолжить' или очистите.",
            parse_mode="HTML",
        )
        return

    # Get the highest quality photo or document
    if message.photo:
        photo = message.photo[-1]
    else:
        photo = message.document

    file = await message.bot.get_file(photo.file_id)
    image_bytes = await message.bot.download_file(file.file_path)
    image_data = image_bytes.read()

    # Validate image size (minimum 300x300)
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(image_data))
        width, height = img.size
        if width < 300 or height < 300:
            await message.answer(
                f"❌ Изображение слишком маленькое: {width}×{height}\n"
                "Загрузите фото не менее 300×300 px.",
                parse_mode="HTML",
            )
            return
    except Exception as e:
        logger.error(f"Image validation failed: {e}")
        await message.answer("❌ Не удалось обработать изображение. Попробуйте другое.")
        return

    # Save and get URL
    if message.photo:
        file_ext = "jpg"
    else:
        mime_type = message.document.mime_type
        if mime_type == "image/jpeg":
            file_ext = "jpg"
        elif mime_type == "image/png":
            file_ext = "png"
        elif mime_type == "image/webp":
            file_ext = "webp"
        else:
            file_ext = "png"
    image_url = save_uploaded_file(image_data, file_ext, is_reference=True)

    if image_url:
        reference_images.append(image_url)
        await state.update_data(reference_images=reference_images)

        preset_id = data.get("preset_id", "new")
        current_count = len(reference_images)

        if data.get("feed_retry_task_id"):
            try:
                await message.delete()
            except Exception:
                pass
            text = _build_feed_retry_upload_text(
                data.get("feed_retry_prompt") or "", current_count, max_refs
            )
            control_message_id = data.get("feed_retry_control_message_id")
            if control_message_id:
                new_message_id = await _edit_feed_retry_control_by_id(
                    message.bot,
                    message.chat.id,
                    control_message_id,
                    text,
                    get_reference_images_upload_keyboard(
                        current_count, max_refs, "feed_retry"
                    ),
                )
                await state.update_data(feed_retry_control_message_id=new_message_id)
            else:
                sent = await message.answer(
                    text,
                    reply_markup=get_reference_images_upload_keyboard(
                        current_count, max_refs, "feed_retry"
                    ),
                    parse_mode="HTML",
                )
                await state.update_data(feed_retry_control_message_id=sent.message_id)
            logger.info(f"Feed retry reference photo {current_count} added: {image_url}")
            return

        title = (
            "🧬 <b>Фото для микса</b>"
            if data.get("mix_mode")
            else "📎 <b>Загрузка референсов</b>"
        )
        text = (
            f"{title}\n\n"
            f"Загружено: <code>{current_count}/{max_refs}</code>\n"
            "✅ Фото добавлено!\n\n"
            "Отправьте следующее или нажмите кнопку ниже:"
        )

        try:
            await message.reply(
                text,
                reply_markup=get_reference_images_upload_keyboard(
                    current_count, max_refs, preset_id
                ),
                parse_mode="HTML",
            )
        except:
            await message.answer(
                text,
                reply_markup=get_reference_images_upload_keyboard(
                    current_count, max_refs, preset_id
                ),
                parse_mode="HTML",
            )
        logger.info(f"Reference photo {current_count} added: {image_url}")
    else:
        await message.answer("❌ Не удалось сохранить фото. Попробуйте ещё раз.")


@router.callback_query(
    GenerationStates.confirming_prompt_improvement,
    F.data.in_({"image_prompt_safe", "image_prompt_original"}),
)
async def handle_image_prompt_improvement_choice(
    callback: types.CallbackQuery, state: FSMContext
):
    """Runs image generation after the user chooses prompt improvement mode."""
    data = await state.get_data()
    prompt = (data.get("pending_image_prompt") or "").strip()
    if not prompt:
        await callback.answer("Промпт не найден, введите его ещё раз", show_alert=True)
        await state.set_state(GenerationStates.waiting_for_input)
        return

    improve = callback.data == "image_prompt_safe"
    await callback.answer("Готовлю генерацию...")
    await handle_image_prompt_text(
        callback.message,
        state,
        prompt_override=prompt,
        improve_prompt=improve,
        telegram_id_override=callback.from_user.id,
    )


@router.callback_query(
    GenerationStates.confirming_prompt_improvement,
    F.data == "image_prompt_back",
)
async def handle_image_prompt_back(callback: types.CallbackQuery, state: FSMContext):
    """Returns from prompt confirmation to image settings."""
    data = await state.get_data()
    current_service, current_options, reference_images = await _sync_image_state(state)
    await callback.message.edit_text(
        _build_image_creation_text(
            current_service,
            current_options,
            reference_images,
            data.get("img_count", 1),
        ),
        reply_markup=get_create_image_keyboard(
            current_service=current_service,
            current_ratio=current_options["aspect_ratio"],
            num_refs=len(reference_images),
            current_options=current_options,
            img_count=data.get("img_count", 1),
        ),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.message(GenerationStates.waiting_for_input, F.text)
async def handle_image_prompt_text(
    message: types.Message,
    state: FSMContext,
    *,
    prompt_override: str | None = None,
    improve_prompt: bool | None = None,
    telegram_id_override: int | None = None,
):
    """Handles text prompt for image generation in waiting_for_input state"""
    data = await state.get_data()
    if data.get("generation_type") != "image":
        return  # Not for images, let other handlers catch

    telegram_id = telegram_id_override or message.from_user.id
    submit_message_id = data.get("submission_id") or getattr(message, "message_id", 0)
    prompt = (prompt_override if prompt_override is not None else message.text).strip()
    if not prompt:
        await message.answer("⚠️ Введите промпт для генерации изображения.")
        return

    if data.get("mix_mode"):
        reference_images = data.get("reference_images", [])
        if not reference_images:
            await message.answer(
                "🧬 Для микса загрузите хотя бы 1 фото-референс и нажмите «Продолжить».",
                reply_markup=get_reference_images_upload_keyboard(
                    0, 14, data.get("preset_id", "new")
                ),
                parse_mode="HTML",
            )
            await state.set_state(GenerationStates.uploading_reference_images)
            return

        mix_options = normalize_image_options(
            "banana_2",
            {"aspect_ratio": data.get("img_ratio"), **data.get("img_options", {})},
        )
        await state.update_data(
            img_service="banana_2",
            img_ratio=mix_options["aspect_ratio"],
            img_options=mix_options,
            img_count=1,
        )
        data = {
            **data,
            "img_service": "banana_2",
            "img_options": mix_options,
            "img_count": 1,
        }

    img_service, img_options, reference_images = _get_image_state(data)
    mix_mode = bool(data.get("mix_mode"))

    if improve_prompt is None:
        await state.update_data(
            pending_image_prompt=prompt,
            pending_prompt_owner_id=telegram_id,
            pending_prompt_message_id=submit_message_id,
        )
        await message.answer(
            _build_prompt_safety_text(prompt),
            reply_markup=get_prompt_safety_keyboard(),
            parse_mode="HTML",
        )
        await state.set_state(GenerationStates.confirming_prompt_improvement)
        return

    if improve_prompt:
        original_prompt = prompt
        prompt = await _improve_image_prompt(
            prompt,
            ref_count=len(reference_images),
            mix_mode=mix_mode,
        )
        if prompt != original_prompt:
            await _send_long_text(
                message,
                "🪄 <b>Безопасный промпт готов</b>",
                prompt,
            )

    prompt = _apply_face_preservation_prompt(
        prompt,
        data.get("face_preservation_mode", "strict" if reference_images else "none"),
        len(reference_images),
    )

    if mix_mode:
        generation_jobs = []
        for model_id in MIX_PHOTO_MODELS:
            model_options = normalize_image_options(
                model_id,
                {
                    "aspect_ratio": img_options.get("aspect_ratio"),
                    **data.get("img_options", {}),
                },
            )
            generation_jobs.append(
                {
                    "model": model_id,
                    "options": model_options,
                    "cost": preset_manager.get_generation_cost(model_id),
                }
            )
    else:
        img_count = data.get("img_count", 1)
        cost = preset_manager.get_generation_cost(img_service)
        generation_jobs = [
            {"model": img_service, "options": img_options, "cost": cost}
            for _ in range(img_count)
        ]

    user = await get_or_create_user(telegram_id)
    total_cost = sum(job["cost"] for job in generation_jobs)
    img_count = len(generation_jobs)

    generation_lock = await generation_lock_guard.acquire(telegram_id)
    if not generation_lock:
        await message.answer("⏳ Предыдущая генерация ещё запускается. Подождите несколько секунд и попробуйте снова.")
        return

    processing_msg = None
    try:
        charged, billing_source, subscription_usage_id = await _charge_generation_or_free_token(
            telegram_id,
            total_cost,
            reason="image_generation_charge",
            external_id=f"image_submit:{telegram_id}:{submit_message_id}",
            usage_type="image",
            model="mix_photo" if mix_mode else img_service,
            metadata={
                "model": "mix_photo" if mix_mode else img_service,
                "models": [job["model"] for job in generation_jobs],
                "count": img_count,
            },
        )
        if not charged:
            await generation_lock_guard.release(generation_lock)
            await state.clear()
            await message.answer(
                "❌ Не хватает активной подписки, бесплатных генераций или BoomCoin. Генерация не запущена.",
                reply_markup=get_main_menu_keyboard(user.credits),
            )
            return
        billing_cost = 0 if billing_source in {"subscription", "free_generation"} else total_cost

        if mix_mode:
            processing_msg = await message.answer(
                _build_progress_text(
                    title="🧬 <b>Микс фото запускается</b>",
                    percent=8,
                    status="Готовлю референсы и отправляю запросы в 3 нейросети.",
                    eta="Сейчас появятся отдельные прогресс-бары по каждой модели.",
                ),
                parse_mode="HTML",
            )
        elif img_count == 1:
            processing_msg = await message.answer(
                _build_progress_text(
                    title="🖼 <b>Фото запускается</b>",
                    percent=10,
                    status="Проверяю параметры и передаю задачу модели.",
                    eta="Обычно это занимает 1-3 минуты.",
                ),
                parse_mode="HTML",
            )
        else:
            processing_msg = await message.answer(
                _build_progress_text(
                    title="🖼 <b>Параллельная генерация запускается</b>",
                    percent=8,
                    status=f"Готовлю {img_count} вариантов и отправляю их моделям.",
                    eta="Сейчас появятся отдельные прогресс-бары по задачам.",
                ),
                parse_mode="HTML",
            )
    except Exception:
        logger.exception("Image generation setup failed")
        await _refund_generation_charge(
            telegram_id,
            total_cost,
            billing_source=locals().get("billing_source", "none"),
            subscription_usage_id=locals().get("subscription_usage_id"),
            reason="generation_refund",
            external_id=f"image_setup:{telegram_id}:{submit_message_id}",
            metadata={"handler": "image_setup"},
        )
        await generation_lock_guard.release(generation_lock)
        await state.clear()
        await message.answer("❌ Ошибка запуска генерации. Ресурс возвращён.")
        return

    async def _run_single(idx: int, job: dict) -> None:
        job_model = job["model"]
        job_options = job["options"]
        job_cost = job["cost"]
        local_tid = f"img_{uuid.uuid4().hex[:12]}"
        await add_generation_task(
            user.id,
            telegram_id,
            local_tid,
            "image",
            job_model,
            model=job_model,
            aspect_ratio=job_options["aspect_ratio"],
            prompt=prompt,
            cost=job_cost,
            reference_images=_serialize_reference_images(reference_images),
            source_feed_task_id=data.get("source_feed_task_id"),
            billing_source=locals().get("billing_source", "credits"),
            subscription_usage_id=locals().get("subscription_usage_id"),
        )
        try:
            callback_url = config.kie_notification_url if config.WEBHOOK_HOST else None
            if job_model == "banana_2":
                result = await nano_banana_2_service.generate_image(
                    prompt=prompt,
                    aspect_ratio=job_options["aspect_ratio"],
                    resolution=job_options["resolution"],
                    output_format=job_options["output_format"],
                    image_input=reference_images,
                    callback_url=callback_url,
                )
            elif job_model == "banana_pro":
                result = await nano_banana_pro_service.generate_image(
                    prompt=prompt,
                    aspect_ratio=job_options["aspect_ratio"],
                    resolution=job_options["resolution"],
                    output_format=job_options["output_format"],
                    image_input=reference_images,
                    callback_url=callback_url,
                )
            elif job_model in ["seedream_edit", "seedream_5_lite"]:
                model_config = get_image_model_config(job_model)
                result = await seedream_service.generate_image(
                    prompt=prompt,
                    model=model_config["api_model"],
                    aspect_ratio=job_options["aspect_ratio"],
                    quality=job_options.get("quality", "basic"),
                    nsfw_checker=job_options.get("nsfw_checker", False),
                    image_urls=reference_images,
                    callback_url=callback_url,
                )
            elif job_model == "gpt_image_2":
                result = await gpt_image_service.generate_image(
                    prompt=prompt,
                    image_urls=reference_images,
                    aspect_ratio=job_options["aspect_ratio"],
                    nsfw_checker=job_options.get("nsfw_checker", False),
                    callback_url=callback_url,
                )
            elif job_model == "grok_t2i":
                result = await grok_service.generate_text_to_image(
                    prompt=prompt,
                    aspect_ratio=job_options["aspect_ratio"],
                    enable_pro=job_options.get("enable_pro", False),
                    nsfw_checker=job_options.get("nsfw_checker", False),
                    callback_url=callback_url,
                )
            elif job_model == "grok_i2i":
                if reference_images:
                    result = await grok_service.generate_image_to_image(
                        image_url=reference_images[0],
                        prompt=prompt,
                        nsfw_checker=job_options.get("nsfw_checker", False),
                        callback_url=callback_url,
                    )
                else:
                    result = await grok_service.generate_text_to_image(
                        prompt=prompt,
                        aspect_ratio=job_options["aspect_ratio"],
                        nsfw_checker=job_options.get("nsfw_checker", False),
                        callback_url=callback_url,
                    )
            elif job_model == "ideogram_character":
                if not reference_images:
                    result = None
                else:
                    result = await ideogram_service.generate_character(
                        prompt=prompt,
                        reference_image_urls=reference_images,
                        aspect_ratio=job_options["aspect_ratio"],
                        rendering_speed=job_options.get(
                            "rendering_speed", "BALANCED"
                        ),
                        style=job_options.get("style", "AUTO"),
                        expand_prompt=job_options.get("expand_prompt", True),
                        num_images=job_options.get("num_images", "1"),
                        nsfw_checker=job_options.get("nsfw_checker", False),
                        callback_url=callback_url,
                    )
            else:
                result = await nano_banana_pro_service.generate_image(
                    prompt=prompt,
                    aspect_ratio=job_options["aspect_ratio"],
                    image_input=reference_images,
                    callback_url=callback_url,
                )

            model_label = get_image_model_config(job_model)["label"]
            prefix = f"[{idx}/{img_count}] " if img_count > 1 else ""

            if isinstance(result, dict) and "task_id" in result:
                api_task_id = result["task_id"]
                import aiosqlite

                from bot.database import DATABASE_PATH

                async with aiosqlite.connect(DATABASE_PATH) as db:
                    await db.execute(
                        "UPDATE generation_tasks SET task_id = ? WHERE task_id = ? AND user_id = ?",
                        (api_task_id, local_tid, user.id),
                    )
                    await db.commit()
                progress_msg = await message.answer(
                    _build_progress_text(
                        title=f"🚀 <b>{html.escape(prefix + model_label)}</b>",
                        percent=20,
                        status="Модель приняла задачу. Работа идёт.",
                        task_id=api_task_id,
                        eta="Результат придёт сюда автоматически.",
                    ),
                    parse_mode="HTML",
                )
                asyncio.create_task(
                    _simulate_generation_progress(
                        progress_msg,
                        api_task_id,
                        title=f"🚀 <b>{html.escape(prefix + model_label)}</b>",
                        eta="Результат придёт сюда автоматически.",
                        steps=(
                            (35, "Модель разбирает промпт и референсы."),
                            (55, "Собирает композицию и детали."),
                            (75, "Доводит изображение до финального вида."),
                            (90, "Почти готово, ждём файл от сервиса."),
                        ),
                        interval=12,
                    )
                )
            elif result:
                saved_url = save_uploaded_file(result, "png")
                retry_kb = get_image_result_keyboard(local_tid, saved_url)
                await message.answer_photo(
                    photo=types.BufferedInputFile(result, filename="generated.png"),
                    caption=f"✅ {prefix}{model_label}: готово!\n💰 <code>{job_cost}</code>🪙",
                    parse_mode="HTML",
                    reply_markup=retry_kb,
                )
                await _send_original_document(
                    message.answer_document, result, saved_url
                )
                await complete_video_task(local_tid, saved_url)
            else:
                if locals().get("billing_source") == "credits" and not config.is_admin(telegram_id):
                    await add_credits_once(telegram_id, job_cost, reason="generation_refund", external_id=local_tid)
                await complete_video_task(local_tid, None)
                await message.answer(f"❌ {prefix}{model_label}: ошибка генерации. Ресурс возвращён.")

        except Exception as e:
            logger.exception(f"Image generation error (idx={idx}): {e}")
            if locals().get("billing_source") == "credits" and not config.is_admin(telegram_id):
                await add_credits_once(telegram_id, job_cost, reason="generation_refund", external_id=local_tid)
            await complete_video_task(local_tid, None)
            await message.answer(f"❌ Ошибка генерации #{idx}.")

    try:
        await asyncio.gather(
            *[_run_single(i + 1, job) for i, job in enumerate(generation_jobs)]
        )
    finally:
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await generation_lock_guard.release(generation_lock)

    await state.clear()


@router.callback_query(F.data == "feed_retry_edit_prompt")
async def handle_feed_retry_edit_prompt(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("feed_retry_task_id"):
        await callback.answer("Пост для повтора не найден", show_alert=True)
        return

    await state.update_data(feed_retry_control_message_id=callback.message.message_id)
    text = (
        "✏️ <b>Изменить промпт</b>\n\n"
        "Отправьте новый текст промпта одним сообщением.\n"
        "Например: замените «брюнетка» на «блондинка» или добавьте нужные детали."
    )
    control_message_id = await _edit_feed_retry_control_message(
        callback,
        text,
        get_reference_images_upload_keyboard(
            len(data.get("reference_images", [])), 14, "feed_retry"
        ),
    )
    if control_message_id:
        await state.update_data(feed_retry_control_message_id=control_message_id)
    await state.set_state(GenerationStates.waiting_for_feed_retry_prompt)
    await callback.answer()


@router.callback_query(F.data == "feed_retry_full_prompt")
async def handle_feed_retry_full_prompt(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("feed_retry_task_id")
    if not task_id:
        await callback.answer("Пост для повтора не найден", show_alert=True)
        return

    prompt = (data.get("feed_retry_prompt") or "").strip()
    if not prompt:
        task = await get_task_by_id(task_id)
        prompt = (task.prompt if task else "") or ""
    if not prompt:
        await callback.answer("Промпт недоступен", show_alert=True)
        return

    control_message_id = await _edit_feed_retry_control_message(
        callback,
        _build_feed_retry_full_prompt_text(prompt),
        _get_feed_retry_prompt_actions_keyboard(),
    )
    if control_message_id:
        await state.update_data(
            feed_retry_prompt=prompt,
            feed_retry_control_message_id=control_message_id,
        )
    await callback.answer()


@router.callback_query(F.data == "feed_retry_back_to_setup")
async def handle_feed_retry_back_to_setup(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("feed_retry_task_id"):
        await callback.answer("Пост для повтора не найден", show_alert=True)
        return

    await state.update_data(feed_retry_control_message_id=callback.message.message_id)
    if data.get("reference_images"):
        await _refresh_image_creation_screen(callback, state)
        await state.set_state(GenerationStates.confirming_reference_images)
    else:
        text = _build_feed_retry_upload_text(data.get("feed_retry_prompt") or "", 0, 14)
        control_message_id = await _edit_feed_retry_control_message(
            callback,
            text,
            get_reference_images_upload_keyboard(0, 14, "feed_retry"),
        )
        if control_message_id:
            await state.update_data(feed_retry_control_message_id=control_message_id)
        await state.set_state(GenerationStates.uploading_reference_images)
    await callback.answer()


@router.message(GenerationStates.waiting_for_feed_retry_prompt, F.text)
async def process_feed_retry_prompt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    prompt = (message.text or "").strip()
    if not prompt:
        await message.answer("Отправьте текст промпта одним сообщением.")
        return

    await state.update_data(feed_retry_prompt=prompt)
    try:
        await message.delete()
    except Exception:
        pass

    refs = data.get("reference_images", [])
    control_message_id = data.get("feed_retry_control_message_id")
    if refs:
        current_service, current_options, reference_images = await _sync_image_state(state)
        img_count = data.get("img_count", 1)
        text = _build_feed_retry_model_text(
            current_service,
            current_options,
            reference_images,
            prompt,
            img_count,
        )
        markup = get_create_image_keyboard(
            current_service=current_service,
            current_ratio=current_options["aspect_ratio"],
            num_refs=len(reference_images),
            current_options=current_options,
            img_count=img_count,
            launch_callback_data="feed_retry_run",
            launch_text="🚀 Запустить повтор",
            edit_prompt_callback_data="feed_retry_edit_prompt",
            full_prompt_callback_data="feed_retry_full_prompt",
        )
        if control_message_id:
            new_message_id = await _edit_feed_retry_control_by_id(
                message.bot, message.chat.id, control_message_id, text, markup
            )
            await state.update_data(feed_retry_control_message_id=new_message_id)
        else:
            sent = await message.answer(text, reply_markup=markup, parse_mode="HTML")
            await state.update_data(feed_retry_control_message_id=sent.message_id)
        await state.set_state(GenerationStates.confirming_reference_images)
        return

    text = _build_feed_retry_upload_text(prompt, 0, 14)
    markup = get_reference_images_upload_keyboard(0, 14, "feed_retry")
    if control_message_id:
        new_message_id = await _edit_feed_retry_control_by_id(
            message.bot, message.chat.id, control_message_id, text, markup
        )
        await state.update_data(feed_retry_control_message_id=new_message_id)
    else:
        sent = await message.answer(text, reply_markup=markup, parse_mode="HTML")
        await state.update_data(feed_retry_control_message_id=sent.message_id)
    await state.set_state(GenerationStates.uploading_reference_images)


@router.callback_query(F.data == "feed_retry_choose_model")
async def handle_feed_retry_choose_model(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("feed_retry_task_id")
    refs = data.get("reference_images", [])
    if not task_id:
        await callback.answer("Пост для повтора не найден", show_alert=True)
        return
    if not refs:
        await callback.answer("Загрузите хотя бы один референс", show_alert=True)
        return

    task = await get_task_by_id(task_id)
    if not task or not task.prompt:
        await callback.answer("Пост уже недоступен", show_alert=True)
        return

    await state.update_data(
        generation_type="image",
        source_feed_task_id=task.task_id,
        preset_id="feed_retry",
        feed_retry_prompt=data.get("feed_retry_prompt") or task.prompt,
    )
    await _refresh_image_creation_screen(callback, state)
    await callback.answer()
    await state.set_state(GenerationStates.confirming_reference_images)


@router.callback_query(F.data == "feed_retry_run")
async def handle_feed_retry_run(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("feed_retry_task_id")
    refs = data.get("reference_images", [])
    if not task_id:
        await callback.answer("Пост для повтора не найден", show_alert=True)
        return
    if not refs:
        await callback.answer("Загрузите хотя бы один референс", show_alert=True)
        return

    task = await get_task_by_id(task_id)
    if not task or not task.prompt:
        await callback.answer("Пост уже недоступен", show_alert=True)
        return

    prompt = (data.get("feed_retry_prompt") or task.prompt).strip()
    await state.update_data(
        generation_type="image",
        source_feed_task_id=task.task_id,
        submission_id=f"feed_retry:{task.task_id}:{callback.id}",
        feed_retry_prompt=prompt,
    )
    await callback.answer("🚀 Запускаю повтор...")
    await handle_image_prompt_text(
        callback.message,
        state,
        prompt_override=prompt,
        improve_prompt=False,
        telegram_id_override=callback.from_user.id,
    )


@router.callback_query(F.data.startswith("retry_img_"))
async def handle_retry_image(callback: types.CallbackQuery, state: FSMContext):
    """Повторяет генерацию фото с теми же параметрами."""
    task_id = callback.data.replace("retry_img_", "")
    task = await get_task_by_id(task_id)

    if not task or not task.prompt:
        await callback.answer("❌ Нет данных для повтора", show_alert=True)
        return

    img_service = task.model or "banana_pro"
    aspect_ratio = task.aspect_ratio or "1:1"
    cost = task.cost or preset_manager.get_generation_cost(img_service)
    img_options = normalize_image_options(img_service, {"aspect_ratio": aspect_ratio})
    prompt = task.prompt
    reference_images = _deserialize_reference_images(task.reference_images)
    if not reference_images:
        reference_images = _extract_reference_images_from_message(callback.message)
    source_feed_task_id = task.source_feed_task_id
    if task.is_public_feed and task.telegram_id != callback.from_user.id:
        source_feed_task_id = task.task_id

    model_config = get_image_model_config(img_service)
    if model_config.get("requires_refs") and not reference_images:
        await callback.answer("❌ Не нашёл исходники для повтора", show_alert=True)
        return

    user = await get_or_create_user(callback.from_user.id)

    generation_lock = await generation_lock_guard.acquire(callback.from_user.id)
    if not generation_lock:
        await callback.answer("⏳ Предыдущая генерация ещё запускается", show_alert=True)
        return

    local_task_id = f"img_{uuid.uuid4().hex[:12]}"
    processing_msg = None
    try:
        await callback.answer("🔄 Запускаю повтор...")
        charged, billing_source, subscription_usage_id = await _charge_generation_or_free_token(
            callback.from_user.id,
            cost,
            reason="image_retry_charge",
            external_id=f"retry:{task_id}:{callback.id}",
            usage_type="image",
            model=img_service,
            metadata={"model": img_service, "source_task_id": task_id},
        )
        if not charged:
            await generation_lock_guard.release(generation_lock)
            await callback.message.answer(
                "❌ Не хватает активной подписки, бесплатных генераций или BoomCoin. Повтор не запущен."
            )
            return

        await add_generation_task(
            user.id,
            callback.from_user.id,
            local_task_id,
            "image",
            img_service,
            model=img_service,
            aspect_ratio=aspect_ratio,
            prompt=prompt,
            cost=0 if billing_source in {"subscription", "free_generation"} else cost,
            reference_images=_serialize_reference_images(reference_images),
            source_feed_task_id=source_feed_task_id,
            billing_source=billing_source,
            subscription_usage_id=subscription_usage_id,
        )

        processing_msg = await callback.message.answer("🔄 Повторяю генерацию...")
    except Exception:
        logger.exception("Retry image setup failed")
        await _refund_generation_charge(
            callback.from_user.id,
            cost,
            billing_source=locals().get("billing_source", "none"),
            subscription_usage_id=locals().get("subscription_usage_id"),
            reason="generation_refund",
            external_id=local_task_id,
            metadata={"handler": "retry_image_setup"},
        )
        await generation_lock_guard.release(generation_lock)
        await callback.message.answer("❌ Ошибка запуска повтора. Ресурс возвращён.")
        return

    try:
        callback_url = config.kie_notification_url if config.WEBHOOK_HOST else None

        if img_service == "banana_2":
            result = await nano_banana_2_service.generate_image(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                resolution=img_options.get("resolution", "4K"),
                output_format=img_options.get("output_format", "png"),
                image_input=reference_images,
                callback_url=callback_url,
            )
        elif img_service == "banana_pro":
            result = await nano_banana_pro_service.generate_image(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                resolution=img_options.get("resolution", "4K"),
                output_format=img_options.get("output_format", "png"),
                image_input=reference_images,
                callback_url=callback_url,
            )
        elif img_service in ("seedream_edit", "seedream_5_lite"):
            result = await seedream_service.generate_image(
                prompt=prompt,
                model=model_config["api_model"],
                aspect_ratio=aspect_ratio,
                quality=img_options.get("quality", "basic"),
                nsfw_checker=img_options.get("nsfw_checker", False),
                image_urls=reference_images,
                callback_url=callback_url,
            )
        elif img_service == "gpt_image_2":
            result = await gpt_image_service.generate_image(
                prompt=prompt,
                image_urls=reference_images,
                aspect_ratio=aspect_ratio,
                nsfw_checker=img_options.get("nsfw_checker", False),
                callback_url=callback_url,
            )
        elif img_service in ("grok_t2i", "grok_i2i"):
            if img_service == "grok_i2i" and reference_images:
                result = await grok_service.generate_image_to_image(
                    image_url=reference_images[0],
                    prompt=prompt,
                    nsfw_checker=img_options.get("nsfw_checker", False),
                    callback_url=callback_url,
                )
            else:
                result = await grok_service.generate_text_to_image(
                    prompt=prompt,
                    aspect_ratio=aspect_ratio,
                    nsfw_checker=img_options.get("nsfw_checker", False),
                    callback_url=callback_url,
                )
        else:
            result = await nano_banana_pro_service.generate_image(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                image_input=reference_images,
                callback_url=callback_url,
            )

        await processing_msg.delete()

        if isinstance(result, dict) and "task_id" in result:
            api_task_id = result["task_id"]
            import aiosqlite

            from bot.database import DATABASE_PATH

            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute(
                    "UPDATE generation_tasks SET task_id = ? WHERE task_id = ? AND user_id = ?",
                    (api_task_id, local_task_id, user.id),
                )
                await db.commit()
            await callback.message.answer(
                f"🚀 Повтор запущен!\n🆔 <code>{api_task_id}</code>\n"
                f"💰 {_format_billing_status(cost, locals().get('billing_source', 'credits'))}\n"
                "Ожидайте результат (1-3 мин).",
                parse_mode="HTML",
            )
        elif result:  # bytes
            saved_url = save_uploaded_file(result, "png")
            retry_kb = get_image_result_keyboard(local_task_id, saved_url)
            await callback.message.answer_photo(
                photo=types.BufferedInputFile(result, filename="generated.png"),
                caption=f"✅ Готово!\n💰 {_format_billing_status(cost, locals().get('billing_source', 'credits'))}",
                parse_mode="HTML",
                reply_markup=retry_kb,
            )
            await _send_original_document(
                callback.message.answer_document, result, saved_url
            )
            await complete_video_task(local_task_id, saved_url)
        else:
            await _refund_generation_charge(
                callback.from_user.id,
                cost,
                billing_source=locals().get("billing_source", "none"),
                subscription_usage_id=locals().get("subscription_usage_id"),
                reason="generation_refund",
                external_id=local_task_id if "local_task_id" in locals() else f"retry:{task_id}",
                metadata={"handler": "retry_image_empty_result"},
            )
            await complete_video_task(local_task_id, None)
            await callback.message.answer("❌ Ошибка повтора. Ресурс возвращён.")

    except Exception as e:
        logger.exception(f"Retry image error: {e}")
        await _refund_generation_charge(
            callback.from_user.id,
            cost,
            billing_source=locals().get("billing_source", "none"),
            subscription_usage_id=locals().get("subscription_usage_id"),
            reason="generation_refund",
            external_id=local_task_id,
            metadata={"handler": "retry_image"},
        )
        await complete_video_task(local_task_id, None)
        await callback.message.answer("❌ Ошибка повтора.")
    finally:
        await generation_lock_guard.release(generation_lock)


@router.message(GenerationStates.waiting_for_reference_video)
async def invalid_reference_video_input(message: types.Message, state: FSMContext):
    """
    Обрабатывает невалидный ввод в состоянии waiting_for_reference_video.
    """
    await message.answer(
        "⚠️ Пожалуйста, отправьте видео файл (макс 50MB)."
        "Это видео будет использовано как референс для стиля/движения."
    )


@router.callback_query(F.data.startswith("v_mode_"))
async def handle_v_mode(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик режимов видео (720p/1080p)"""
    mode = callback.data.replace("v_mode_", "")
    await state.update_data(v_mode=mode)
    await _show_video_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data.startswith("v_orientation_"))
async def handle_v_orientation(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик ориентации видео (image/video)"""
    orientation = callback.data.replace("v_orientation_", "")
    await state.update_data(v_orientation=orientation)
    await _show_video_creation_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data.startswith("motion_mode_"))
async def handle_motion_mode(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик режимов Motion Control"""
    mode = callback.data.replace("motion_mode_", "")
    await state.update_data(motion_mode=mode)
    data = await state.get_data()
    current_orientation = data.get("motion_orientation", "video")
    await callback.message.edit_reply_markup(
        get_motion_control_keyboard(mode, current_orientation)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("motion_orientation_"))
async def handle_motion_orientation(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик ориентации Motion Control"""
    orientation = callback.data.replace("motion_orientation_", "")
    await state.update_data(motion_orientation=orientation)
    data = await state.get_data()
    current_mode = data.get("motion_mode", "720p")
    await callback.message.edit_reply_markup(
        get_motion_control_keyboard(current_mode, orientation)
    )
    await callback.answer()


@router.message(GenerationStates.waiting_for_video_prompt, F.text)
async def handle_video_prompt_text(message: types.Message, state: FSMContext):
    """Обрабатывает ввод промпта для видео и motion control (новый UX)."""
    logger.info(f"[DEBUG STATE] Current state: {await state.get_state()}")
    logger.info(f"Video prompt handler triggered for user {message.from_user.id}")
    prompt = message.text.strip()

    if not prompt:
        await message.answer("⚠️ Введите описание видео перед запуском генерации.")
        return

    data = await state.get_data()
    generation_type = data.get("generation_type", "")
    logger.info(f"Generation type: {generation_type}")

    await state.update_data(user_prompt=prompt)

    if generation_type == "motion_control":
        logger.info("Calling run_motion_control")
        await run_motion_control(message, state, prompt)
    else:
        logger.info("Calling run_no_preset_video_from_message")
        await run_no_preset_video_from_message(message, state, prompt)


async def run_no_preset_video_from_message(
    message: types.Message | types.CallbackQuery, state: FSMContext, prompt: str
):
    """Запускает видео генерацию без пресета (новый UX с v_type, v_model и т.д.)"""
    target_message = message.message if isinstance(message, types.CallbackQuery) else message
    telegram_id = message.from_user.id
    submit_message_id = getattr(target_message, "message_id", 0)
    data = await state.get_data()
    v_type = data.get("v_type", "text")
    v_model = data.get("v_model", "v3_std")
    video_urls = data.get("v_reference_videos", [])
    if video_urls and v_model not in {"happyhorse_edit", "glow", "gemini_omni"}:
        v_model = "aleph"
    if v_type == "video" and v_model not in _MODELS_VIDEO:
        v_model = "aleph"
    v_duration = int(data.get("v_duration", 5))
    video_options = normalize_video_options(v_model, data.get("video_options", {}))
    # Cap duration for imgtxt except for models with their own duration logic
    _no_cap_models = (
        "grok_imagine",
        "seedance2",
        "veo3_fast",
        "veo3",
        "veo3_lite",
        "hailuo_23_pro",
        "hailuo_23_std",
        "hailuo_pro",
        "hailuo_std",
        "hailuo_i2v_pro",
        "hailuo_i2v_std",
        "happyhorse_t2v",
        "happyhorse_i2v",
        "happyhorse_ref2v",
        "happyhorse_edit",
        "wan_27_t2v",
        "wan_27_i2v",
        "gemini_omni",
    )
    if v_type == "imgtxt" and v_model not in _no_cap_models:
        v_duration = min(v_duration, 10)
    v_ratio = data.get("v_ratio", "16:9")
    v_image_url = data.get("v_image_url")
    v_video_url = data.get("v_video_url")

    image_url = data.get("v_image_url")
    video_urls = (
        data.get("v_reference_videos", [])
        if v_model == "gemini_omni" or v_type == "video"
        else None
    )
    image_refs = data.get("reference_images", [])
    if v_model == "gemini_omni" and video_urls:
        v_duration = 4

    elements_list = None
    kling_image_input = image_refs if v_type != "imgtxt" else None
    if v_type == "imgtxt" and image_refs:
        element_refs = image_refs[:12]
        if len(element_refs) == 1:
            element_refs = [element_refs[0], element_refs[0]]
        elements_list = [
            {
                "description": "reference photos for video generation consistency and style",
                "reference_image_urls": element_refs,
            }
        ]

    cost = preset_manager.get_video_cost(v_model, v_duration)

    user = await get_or_create_user(telegram_id)
    is_admin = config.is_admin(telegram_id)

    generation_lock = None

    # Admin free access
    if is_admin:
        logger.info(
            f"Admin {telegram_id} - free access (skipped {cost} credits)"
        )
    else:
        generation_lock = await generation_lock_guard.acquire(telegram_id)
        if not generation_lock:
            await target_message.answer("⏳ Предыдущая генерация ещё запускается. Подождите несколько секунд и попробуйте снова.")
            await state.clear()
            return
        charged, billing_source, subscription_usage_id = await _charge_generation_or_free_token(
            telegram_id,
            cost,
            reason="video_generation_charge",
            external_id=f"video_submit:{telegram_id}:{submit_message_id}",
            usage_type="video",
            model=v_model,
            metadata={"model": v_model, "duration": v_duration, "ratio": v_ratio},
        )
        if not charged:
            await generation_lock_guard.release(generation_lock)
            await state.clear()
            await target_message.answer(
                "❌ Не хватает активной подписки с видео, бесплатных генераций или BoomCoin. Генерация не запущена.",
                reply_markup=get_main_menu_keyboard(await get_user_credits(telegram_id)),
            )
            return

    refund_external_id = f"video:{telegram_id}:{submit_message_id}"
    current_billing_source = locals().get("billing_source", "none")
    current_subscription_usage_id = locals().get("subscription_usage_id")

    async def refund_current_video_charge(handler: str) -> None:
        if is_admin:
            return
        await _refund_generation_charge(
            telegram_id,
            cost,
            billing_source=current_billing_source,
            subscription_usage_id=current_subscription_usage_id,
            reason="generation_refund",
            external_id=refund_external_id,
            metadata={"handler": handler},
        )

    processing_msg = None
    try:
        processing_msg = await target_message.answer(
            _build_progress_text(
                title="🎬 <b>Видео запускается</b>",
                percent=10,
                status=(
                    f"Передаю задачу модели {v_model}: "
                    f"{v_duration}s, "
                    f"{'формат по фото' if v_model == 'wan_27_i2v' else v_ratio}, "
                    f"{cost}🪙."
                ),
                eta="Обычно видео занимает 1-5 минут.",
            ),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Video generation setup failed")
        if not is_admin:
            await _refund_generation_charge(
                telegram_id,
                cost,
                billing_source=locals().get("billing_source", "none"),
                subscription_usage_id=locals().get("subscription_usage_id"),
                reason="generation_refund",
                external_id=refund_external_id,
                metadata={"handler": "video_setup"},
            )
        await generation_lock_guard.release(generation_lock)
        await state.clear()
        await target_message.answer("❌ Ошибка запуска генерации. Ресурс возвращён.")
        return

    try:
        from bot.services.kling_service import kling_service

        if v_model == "grok_imagine":
            if not image_url:
                await target_message.answer(
                    "❌ Grok Imagine требует стартовое изображение (фото+текст режим)."
                )
                await refund_current_video_charge("grok_missing_image")
                await processing_msg.delete()
                await generation_lock_guard.release(generation_lock)
                await state.clear()
                return

            # Pass start image + references (max 7 total for Grok)
            grok_image_urls = [image_url] + image_refs[:6]
            grok_duration = v_duration  # Supports 6,20,30 sec
            grok_mode = video_options.get("mode", data.get("grok_mode", "normal"))
            result = await grok_service.generate_image_to_video(
                image_urls=grok_image_urls,
                prompt=prompt,
                mode=grok_mode,
                duration=grok_duration,
                resolution=video_options.get("resolution", "720p"),
                aspect_ratio=v_ratio,
                nsfw_checker=video_options.get("nsfw_checker", False),
                callBackUrl=(
                    config.kling_notification_url if config.WEBHOOK_HOST else None
                ),
            )
        elif v_model == "aleph":
            if not video_urls:
                await target_message.answer(
                    "❌ Aleph Video требует референсное видео (видео+текст режим)."
                )
                await refund_current_video_charge("aleph_missing_video")
                await processing_msg.delete()
                await generation_lock_guard.release(generation_lock)
                await state.clear()
                return
            result = await aleph_service.generate_video(
                prompt=prompt,
                video_url=video_urls[0],
                duration=v_duration,
                aspect_ratio=v_ratio,
                callback_url=(
                    config.kling_notification_url if config.WEBHOOK_HOST else None
                ),
            )
        elif v_model == "runway":
            from bot.services.runway_service import runway_service

            if v_type == "video":
                await target_message.answer(
                    "❌ Runway не поддерживает видео референсы. Используйте текст или фото+текст."
                )
                await refund_current_video_charge("runway_unsupported_video_ref")
                await processing_msg.delete()
                await generation_lock_guard.release(generation_lock)
                await state.clear()
                return
            callback_url = (
                config.kling_notification_url if config.WEBHOOK_HOST else None
            )
            result = await runway_service.generate_video(
                prompt=prompt,
                image_url=image_url,
                duration=v_duration,
                quality=video_options.get("quality", "720p"),
                aspect_ratio=v_ratio,
                callback_url=callback_url,
            )
        elif v_model in ("veo3_fast", "veo3", "veo3_lite"):
            veo_image_urls = []
            if image_url:
                veo_image_urls = [image_url] + image_refs[:1]
            result = await veo_service.generate_video(
                prompt=prompt,
                model=v_model,
                aspect_ratio=v_ratio,
                resolution=video_options.get("resolution", "1080p"),
                enable_translation=video_options.get("enable_translation", True),
                image_urls=veo_image_urls or None,
                callback_url=(
                    config.veo_notification_url if config.WEBHOOK_HOST else None
                ),
            )
        elif v_model == "gemini_omni":
            omni_images = _get_gemini_omni_effective_image_urls(data)
            omni_audio_ids = data.get("omni_audio_ids", [])
            omni_character_ids = data.get("omni_character_ids", [])
            invalid_base_voice_ids = [
                audio_id
                for audio_id in omni_audio_ids
                if str(audio_id).lower() in GEMINI_OMNI_BASE_VOICES
            ]
            if invalid_base_voice_ids:
                await target_message.answer(
                    "❌ В Gemini Omni выбран базовый голос, а нужен созданный Audio ID.\n\n"
                    "Откройте <b>Gemini Omni → Создать голос</b>, создайте голос "
                    "на базе этого preset и повторите запуск.",
                    parse_mode="HTML",
                )
                await refund_current_video_charge("gemini_omni_invalid_voice")
                await processing_msg.delete()
                await generation_lock_guard.release(generation_lock)
                await state.clear()
                return
            if omni_character_ids and not omni_images and not video_urls:
                await target_message.answer(
                    "❌ Для Gemini Omni Character нужен визуальный вход.\n\n"
                    "Если Character ID добавлен вручную, загрузите фото персонажа/сцены "
                    "или создайте персонажа через <b>Gemini Omni → Создать персонажа</b>, "
                    "тогда я автоматически добавлю исходное фото в видеозадачу.",
                    parse_mode="HTML",
                )
                await refund_current_video_charge("gemini_omni_missing_visual")
                await processing_msg.delete()
                await generation_lock_guard.release(generation_lock)
                await state.clear()
                return
            logger.info(
                "Starting Gemini Omni video for user %s with audio_ids=%s character_ids=%s image_count=%s video_count=%s",
                telegram_id,
                omni_audio_ids,
                omni_character_ids,
                len(omni_images),
                len(video_urls or []),
            )
            quota_used = len(omni_images[:GEMINI_OMNI_MAX_IMAGES]) + (
                2 if video_urls else 0
            ) + len(omni_character_ids[:GEMINI_OMNI_MAX_CHARACTER_IDS])
            if quota_used > GEMINI_OMNI_MAX_INPUT_UNITS:
                await target_message.answer(
                    f"❌ Gemini Omni принимает до {GEMINI_OMNI_MAX_INPUT_UNITS} единиц входов: фото=1, видео=2, персонаж=1. "
                    "Уменьшите количество фото или Character ID."
                )
                await refund_current_video_charge("gemini_omni_too_many_inputs")
                await processing_msg.delete()
                await generation_lock_guard.release(generation_lock)
                await state.clear()
                return
            result = await gemini_omni_service.generate_video(
                prompt=prompt,
                image_urls=omni_images,
                video_urls=video_urls or None,
                audio_ids=omni_audio_ids,
                character_ids=omni_character_ids,
                duration=v_duration,
                aspect_ratio=v_ratio,
                resolution=video_options.get("resolution", "720p"),
                seed=video_options.get("seed"),
                callback_url=(
                    config.kie_notification_url if config.WEBHOOK_HOST else None
                ),
            )
        elif v_model in (
            "hailuo_23_pro",
            "hailuo_23_std",
            "hailuo_pro",
            "hailuo_std",
            "hailuo_i2v_pro",
            "hailuo_i2v_std",
        ):
            from bot.services.hailuo_service import HAILUO_IMAGE_REQUIRED

            if v_model in HAILUO_IMAGE_REQUIRED and not image_url:
                await target_message.answer(
                    f"❌ {v_model} требует стартовое изображение (фото+текст режим)."
                )
                await refund_current_video_charge("hailuo_missing_image")
                await processing_msg.delete()
                await generation_lock_guard.release(generation_lock)
                await state.clear()
                return
            result = await hailuo_service.generate_video(
                model_key=v_model,
                prompt=prompt,
                image_url=image_url,
                duration=v_duration,
                resolution=video_options.get(
                    "resolution", data.get("hailuo_resolution", "768P")
                ),
                nsfw_checker=video_options.get("nsfw_checker", False),
                prompt_optimizer=video_options.get("prompt_optimizer", False),
                callback_url=(
                    config.kie_notification_url if config.WEBHOOK_HOST else None
                ),
            )
        elif v_model in (
            "happyhorse_t2v",
            "happyhorse_i2v",
            "happyhorse_ref2v",
            "happyhorse_edit",
        ):
            from bot.services.happyhorse_service import (
                HAPPYHORSE_IMAGE_REQUIRED,
                HAPPYHORSE_VIDEO_REQUIRED,
            )

            happyhorse_images = []
            if image_url:
                happyhorse_images.append(image_url)
            happyhorse_images.extend(image_refs)

            if v_model in HAPPYHORSE_IMAGE_REQUIRED and not happyhorse_images:
                await target_message.answer(
                    f"❌ {v_model} требует минимум одно изображение (фото+текст режим)."
                )
                await refund_current_video_charge("happyhorse_missing_image")
                await processing_msg.delete()
                await generation_lock_guard.release(generation_lock)
                await state.clear()
                return
            if v_model in HAPPYHORSE_VIDEO_REQUIRED and not video_urls:
                await target_message.answer(
                    "❌ HappyHorse Edit требует видео-референс (режим видео+текст)."
                )
                await refund_current_video_charge("happyhorse_missing_video")
                await processing_msg.delete()
                await generation_lock_guard.release(generation_lock)
                await state.clear()
                return

            result = await happyhorse_service.generate_video(
                model_key=v_model,
                prompt=prompt,
                image_urls=happyhorse_images,
                video_url=video_urls[0] if video_urls else None,
                duration=v_duration,
                aspect_ratio=v_ratio,
                resolution=video_options.get("resolution", "1080p"),
                audio_setting=video_options.get("audio_setting", "auto"),
                seed=video_options.get("seed"),
                callback_url=(
                    config.kie_notification_url if config.WEBHOOK_HOST else None
                ),
            )
        elif v_model in {"wan_27_t2v", "wan_27_i2v"}:
            if v_model == "wan_27_i2v" and not image_url:
                await target_message.answer(
                    "❌ Wan 2.7 I2V требует стартовое изображение (фото+текст режим)."
                )
                await refund_current_video_charge("wan_missing_image")
                await processing_msg.delete()
                await generation_lock_guard.release(generation_lock)
                await state.clear()
                return
            result = await kling_service.generate_video(
                prompt=prompt,
                model=v_model,
                duration=v_duration,
                aspect_ratio=v_ratio,
                image_url=image_url,
                seedance_resolution=video_options.get("resolution", "1080p"),
                wan_resolution=video_options.get("resolution", "1080p"),
                wan_prompt_extend=video_options.get("prompt_extend", True),
                wan_watermark=video_options.get("watermark", False),
                webhook_url=(
                    config.kie_notification_url if config.WEBHOOK_HOST else None
                ),
            )
        else:
            result = await kling_service.generate_video(
                prompt=prompt,
                model=v_model,
                duration=v_duration,
                aspect_ratio=v_ratio,
                image_url=image_url,
                video_urls=video_urls,
                image_input=kling_image_input,
                elements=elements_list,
                generate_audio=video_options.get("sound", True),
                seedance_resolution=video_options.get("resolution"),
                seedance_nsfw_checker=video_options.get("nsfw_checker", False),
                seedance_web_search=video_options.get("web_search", False),
                motion_mode=video_options.get(
                    "motion_quality", data.get("v_mode", "720p")
                ),
                motion_orientation=video_options.get(
                    "character_orientation", data.get("v_orientation", "video")
                ),
                keep_original_sound=video_options.get("keep_original_sound", True),
                webhook_url=(
                    config.kling_notification_url if config.WEBHOOK_HOST else None
                ),
            )

        await processing_msg.delete()

        if result and "task_id" in result:
            await add_generation_task(
                user.id,
                telegram_id,
                result["task_id"],
                "video",
                "no_preset_video",
                model=v_model,
                duration=v_duration,
                aspect_ratio=v_ratio,
                prompt=prompt,
                cost=0 if locals().get("billing_source") in {"subscription", "free_generation"} else cost,
                billing_source=locals().get("billing_source", "credits"),
                subscription_usage_id=locals().get("subscription_usage_id"),
            )
            await target_message.answer(
                _build_video_task_started_text(
                    task_id=result["task_id"],
                    model=v_model,
                    duration=v_duration,
                    ratio=v_ratio,
                    cost=cost,
                    is_admin=is_admin,
                ),
                parse_mode="HTML",
            )
            progress_msg = await target_message.answer(
                _build_progress_text(
                    title="🎬 <b>Прогресс видео</b>",
                    percent=20,
                    status="Модель приняла задачу. Работа идёт.",
                    task_id=result["task_id"],
                    eta="Результат придёт сюда автоматически.",
                ),
                parse_mode="HTML",
            )
            asyncio.create_task(
                _simulate_generation_progress(
                    progress_msg,
                    result["task_id"],
                    title="🎬 <b>Прогресс видео</b>",
                    eta="Результат придёт сюда автоматически.",
                    steps=(
                        (30, "Модель строит сцену и движение."),
                        (45, "Генерируются ключевые кадры."),
                        (65, "Склеивается плавное видео."),
                        (82, "Финальная обработка и качество."),
                        (94, "Почти готово, ждём файл от сервиса."),
                    ),
                    interval=18,
                )
            )
        else:
            await refund_current_video_charge("provider_rejected_task")
            error_text = result.get("error") if isinstance(result, dict) else None
            error_code = result.get("code") if isinstance(result, dict) else None
            if v_model == "gemini_omni" and error_text:
                if "audio_id not found" in str(error_text).lower():
                    await target_message.answer(
                        "❌ Gemini Omni не принял Audio ID: он не найден или создан в другом Kie аккаунте.\n\n"
                        "Создайте голос через <b>Gemini Omni → Создать голос</b> "
                        "и повторите запуск. Ресурс возвращён.",
                        parse_mode="HTML",
                    )
                else:
                    await target_message.answer(
                        f"❌ Gemini Omni отклонил задачу"
                        f"{f' (код {error_code})' if error_code else ''}:\n"
                        f"<code>{html.escape(str(error_text))}</code>\n\n"
                        "Ресурс возвращён.",
                        parse_mode="HTML",
                    )
            else:
                await target_message.answer("❌ Не удалось создать задачу. Ресурс возвращён.")
    except Exception as e:
        logger.exception(f"Video generation error: {e}")
        await refund_current_video_charge("provider_exception")
        await target_message.answer("❌ Ошибка генерации. Ресурс возвращён.")

    await generation_lock_guard.release(generation_lock)
    await state.clear()


# =============================================================================
# ОБРАБОТЧИКИ ОПЦИЙ ГЕНЕРАЦИИ (НОВОЕ СОГЛАСНО banana_api.md)
# =============================================================================


@router.callback_query(F.data.startswith("model_"))
async def handle_model_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора модели генерации"""
    parts = callback.data.split("_")
    if len(parts) >= 3:
        preset_id = parts[1]
        model_type = parts[2]  # "flash" или "pro"

        model = (
            "gemini-2.5-flash-image"
            if model_type == "flash"
            else "gemini-3-pro-image-preview"
        )

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["model"] = model
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            model_emoji = "💎" if "pro" in model else "⚡"
            text = f"✅ <b>Модель изменена</b>"
            text += f"{model_emoji} Теперь используется: <code>{model}</code>"

            if model_type == "flash":
                text += "<i>Быстрая генерация, до 1024px</i>\n"
            else:
                text += "<i>Высокое качество, до 4K, с thinking</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("resolution_"))
async def handle_resolution_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора разрешения изображения"""
    parts = callback.data.split("_")
    if len(parts) >= 3:
        preset_id = parts[1]
        resolution = parts[2]  # "1K", "2K", "4K"

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["resolution"] = resolution
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            res_emoji = {"1K": "⚡", "2K": "💎", "4K": "👑"}.get(resolution, "⚡")
            text = f"✅ <b>Разрешение изменено</b>"
            text += f"{res_emoji} Теперь используется: <code>{resolution}</code>"

            resolutions = {
                "1K": "Стандартное качество, 1024px",
                "2K": "HD качество, 2048px",
                "4K": "Максимальное качество, 4096px",
            }
            text += f"<i>{resolutions.get(resolution, '')}</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(
    F.data.startswith("img_ratio_") & ~F.data.startswith("img_ratio_no_preset")
)
async def handle_image_ratio_selection(
    callback: types.CallbackQuery, state: FSMContext
):
    """Обработка выбора формата изображения для пресетов"""
    parts = callback.data.split("_")
    if len(parts) >= 4:
        preset_id = parts[1]
        ratio = f"{parts[2]}:{parts[3]}"  # "16:9"

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["aspect_ratio"] = ratio
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            text = f"✅ <b>Формат изменён</b>"
            text += f"📐 Теперь используется: <code>{ratio}</code>"

            ratios_desc = {
                "1:1": "Квадрат (Instagram, Facebook)",
                "16:9": "Горизонтальный (YouTube)",
                "9:16": "Вертикальный (TikTok, Reels)",
                "4:5": "Портретный (Instagram)",
                "21:9": "Панорамный (Кино)",
            }
            text += f"<i>{ratios_desc.get(ratio, '')}</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("grounding_"))
async def handle_search_grounding(callback: types.CallbackQuery, state: FSMContext):
    """Обработка поискового заземления (Grounding)"""
    parts = callback.data.split("_")
    if len(parts) >= 2:
        preset_id = parts[1]

        # Переключаем опцию
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["enable_search"] = not generation_options.get(
            "enable_search", False
        )
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            enabled = generation_options["enable_search"]
            status = "🟢 ВКЛ" if enabled else "🔴 ВЫКЛ"
            text = f"✅ <b>Поиск в интернете: {status}</b>"

            if enabled:
                text += "<i>AI будет использовать Google Search для актуальной информации</i>\n"
                text += "\nПримеры:\n"
                text += "• Погода на 5 дней\n"
                text += "• Последние новости\n"
                text += "• Актуальные события"
            else:
                text += "<i>Поиск отключён</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("ref_"))
async def handle_reference_images(callback: types.CallbackQuery, state: FSMContext):
    """
    Обработка работы с референсными изображениями (до 14 шт)
    Поддерживает загрузку, управление и подтверждение референсов
    """
    parts = callback.data.split("_")
    action = parts[1] if len(parts) > 1 else ""
    preset_id = parts[2] if len(parts) > 2 else None

    data = await state.get_data()
    current_refs = data.get("reference_images", [])
    max_refs = 14

    if action == "upload":
        # Начинаем загрузку референсных изображений
        await state.set_state(GenerationStates.uploading_reference_images)
        await state.update_data(preset_id=preset_id, reference_images=current_refs)

        await callback.message.edit_text(
            f"📎 <b>Загрузка референсных изображений</b>"
            f"Загружено: <code>{len(current_refs)}/{max_refs}</code>"
            f"Отправьте фотографии (до {max_refs} штук), которые будут использоваться как референсы:\n"
            f"• До 10 объектов с высокой точностью\n"
            f"• До 4 персонажей для консистентности\n"
            f"• До 14 изображений суммарно"
            f"После загрузки нажмите ▶️ Продолжить",
            reply_markup=get_reference_images_upload_keyboard(
                len(current_refs), max_refs, preset_id
            ),
            parse_mode="HTML",
        )

    elif action == "clear":
        # Очищаем все референсы
        await state.update_data(reference_images=[])
        await callback.message.edit_text(
            f"📎 <b>Референсы очищены</b>"
            f"Загружено: <code>0/{max_refs}</code>"
            f"Отправьте фотографии для загрузки референсов:",
            reply_markup=get_reference_images_upload_keyboard(0, max_refs, preset_id),
            parse_mode="HTML",
        )

    elif action == "confirm":
        # Переходим к подтверждению
        if not current_refs:
            await callback.answer("❌ Нет загруженных изображений", show_alert=True)
            return

        # Для нового UX (preset_id == "new") - сразу переходим к выбору модели
        # (пропускаем экран подтверждения референсов)
        if preset_id == "new":
            data = await state.get_data()
            current_service = data.get("img_service", "banana_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>"
                f"Введите промпт для генерации:",
                reply_markup=get_create_image_keyboard(
                    current_service, current_ratio, num_refs=len(current_refs)
                ),
                parse_mode="HTML",
            )
            await callback.answer()
            await state.set_state(GenerationStates.waiting_for_input)
        else:
            # Для пресетов - сразу переходим к экрану пресета (пропускаем экран подтверждения)
            preset = preset_manager.get_preset(preset_id)
            if preset:
                await show_preset_details(
                    callback.message, preset, callback.from_user.id
                )
            else:
                # Fallback - показать параметры генерации
                data = await state.get_data()
                current_service = data.get("img_service", "banana_pro")
                current_ratio = data.get("img_ratio", "1:1")
                await callback.message.edit_text(
                    f"✨ <b>Создание фото</b>"
                    f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                    f"✨ Модель: <code>{current_service}</code>\n"
                    f"📐 Формат: <code>{current_ratio}</code>"
                    f"Введите промпт для генерации:",
                    reply_markup=get_create_image_keyboard(
                        current_service, current_ratio
                    ),
                    parse_mode="HTML",
                )
                await state.set_state(GenerationStates.waiting_for_input)

    elif action == "reload":
        # Перезагружаем — очищаем и начинаем заново
        await state.update_data(reference_images=[])
        await state.set_state(GenerationStates.uploading_reference_images)

        await callback.message.edit_text(
            f"📎 <b>Перезагрузка референсов</b>"
            f"Загружено: <code>0/{max_refs}</code>"
            f"Отправьте новые фотографии для загрузки референсов:",
            reply_markup=get_reference_images_upload_keyboard(0, max_refs, preset_id),
            parse_mode="HTML",
        )

    elif action == "accept":
        # Сохраняем референсы в generation_options
        generation_options = data.get("generation_options", {})
        generation_options["reference_images"] = current_refs
        await state.update_data(generation_options=generation_options)

        # Для нового UX (preset_id == "new") - переходим к экрану выбора модели/формата
        # (пропускаем промежуточное меню подтверждения)
        if preset_id == "new":
            current_service = data.get("img_service", "banana_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>"
                f"Введите промпт для генерации:",
                reply_markup=get_create_image_keyboard(current_service, current_ratio),
                parse_mode="HTML",
            )
            await state.set_state(GenerationStates.waiting_for_input)
        else:
            # Для пресетов - возвращаемся к экрану пресета
            preset = preset_manager.get_preset(preset_id)
            if preset:
                await show_preset_details(
                    callback.message, preset, callback.from_user.id
                )
            else:
                # Этот код не должен достигаться в нормальном потоке, но оставим для совместимости
                await callback.message.edit_text(
                    "✅ Референсы сохранены!",
                    reply_markup=get_back_keyboard("back_main"),
                )

    else:
        # Показываем справку о референсах (стандартное поведение)
        help_text = get_reference_images_help()

        await callback.message.edit_text(
            help_text,
            reply_markup=get_reference_images_keyboard(preset_id),
            parse_mode="HTML",
        )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.message(
    GenerationStates.waiting_for_reference_video,
    F.video | (F.document & F.document.mime_type.startswith("video/")),
)
async def process_reference_video_upload(message: types.Message, state: FSMContext):
    """
    Обрабатывает загрузку референсного видео для режима video (видео+текст → видео).
    Сохраняет видео и переключает в состояние ожидания промпта.
    """
    data = await state.get_data()
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")

    if generation_type == "video" and v_type == "video":
        # Определяем источник файла (video или document)
        if message.video:
            video_obj = message.video
        elif message.document and message.document.mime_type.startswith("video/"):
            video_obj = message.document
        else:
            await message.answer("❌ Неверный тип файла. Отправьте видео.")
            return

        file = await message.bot.get_file(video_obj.file_id)

        # Проверяем размер (макс 20MB для стабильности)
        file_size = getattr(video_obj, "file_size", 0)
        if file_size > 20 * 1024 * 1024:
            await message.answer("❌ Видео слишком большое (макс 20MB).")
            return

        video_bytes = await message.bot.download_file(file.file_path)
        video_data = video_bytes.read()

        # Сохраняем видео и получаем URL
        video_url = save_uploaded_file(video_data, "mp4", is_reference=True)

        if video_url:
            v_reference_videos = data.get("v_reference_videos", [])
            if video_url not in v_reference_videos:
                v_reference_videos = [video_url, *v_reference_videos][:1]
            await state.update_data(
                v_video_url=video_url,
                v_reference_videos=v_reference_videos,
            )
            logger.info(f"Saved reference video for video mode: {video_url}")
        else:
            await message.answer("❌ Не удалось сохранить видео. Попробуйте ещё раз.")
            return

        # Переключаемся в состояние ожидания промпта
        await state.set_state(GenerationStates.waiting_for_video_prompt)

        # Получаем обновлённые данные
        data = await state.get_data()
        current_v_type = data.get("v_type", "video")
        current_model = data.get("v_model", "v26_pro")
        current_duration = data.get("v_duration", 5)
        current_ratio = data.get("v_ratio", "16:9")
        user_prompt = data.get("user_prompt", "")

        # Показываем экран с промптом
        video_status = "\n✅ <b>Референсное видео загружено!</b>\n"

        prompt_display = ""
        if user_prompt:
            prompt_display = f"\n📝 <b>Промпт:</b> <code>{user_prompt[:50]}{'...' if len(user_prompt) > 50 else ''}</code>\n"

        text = (
            f"🎬 <b>Создание видео</b>"
            f"{video_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Видео + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>"
            f"Опишите желаемый эффект/стиль:\n"
            f"• Стиль видео\n"
            f"• Дополнительные эффекты\n"
            f"• Атмосфера"
            f"<i>Видео будет использовано как референс для движения/стиля (@Video1)</i>"
        )

        await message.answer(
            text,
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=current_model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )
        return

    await message.answer("Пожалуйста, отправьте текстовое описание.")


@router.message(GenerationStates.waiting_for_reference_video)
async def invalid_reference_video_input(message: types.Message, state: FSMContext):
    """
    Обрабатывает невалидный ввод в состоянии waiting_for_reference_video.
    """
    await message.answer(
        "⚠️ Пожалуйста, отправьте видеофайл до 50 MB.\n\n"
        "Это видео будет использовано как референс для стиля и движения."
    )


@router.message(GenerationStates.waiting_for_video_prompt, F.text)
async def handle_video_prompt_text(message: types.Message, state: FSMContext):
    """Обрабатывает ввод промпта для видео и motion control (новый UX)."""
    logger.info(f"[DEBUG STATE] Current state: {await state.get_state()}")
    logger.info(f"Video prompt handler triggered for user {message.from_user.id}")
    prompt = message.text.strip()

    if not prompt:
        await message.answer("⚠️ Введите описание видео перед запуском генерации.")
        return

    data = await state.get_data()
    generation_type = data.get("generation_type", "")
    logger.info(f"Generation type: {generation_type}")

    await state.update_data(user_prompt=prompt)

    if generation_type == "motion_control":
        logger.info("Calling run_motion_control")
        await run_motion_control(message, state, prompt)
    else:
        logger.info("Calling run_no_preset_video_from_message")
        await run_no_preset_video_from_message(message, state, prompt)


# =============================================================================
# ОБРАБОТЧИКИ ОПЦИЙ ГЕНЕРАЦИИ (НОВОЕ СОГЛАСНО banana_api.md)
# =============================================================================


@router.callback_query(F.data.startswith("model_"))
async def handle_model_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора модели генерации"""
    parts = callback.data.split("_")
    if len(parts) >= 3:
        preset_id = parts[1]
        model_type = parts[2]  # "flash" или "pro"

        model = (
            "gemini-2.5-flash-image"
            if model_type == "flash"
            else "gemini-3-pro-image-preview"
        )

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["model"] = model
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            model_emoji = "💎" if "pro" in model else "⚡"
            text = f"✅ <b>Модель изменена</b>"
            text += f"{model_emoji} Теперь используется: <code>{model}</code>"

            if model_type == "flash":
                text += "<i>Быстрая генерация, до 1024px</i>\n"
            else:
                text += "<i>Высокое качество, до 4K, с thinking</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("resolution_"))
async def handle_resolution_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора разрешения изображения"""
    parts = callback.data.split("_")
    if len(parts) >= 3:
        preset_id = parts[1]
        resolution = parts[2]  # "1K", "2K", "4K"

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["resolution"] = resolution
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            res_emoji = {"1K": "⚡", "2K": "💎", "4K": "👑"}.get(resolution, "⚡")
            text = f"✅ <b>Разрешение изменено</b>"
            text += f"{res_emoji} Теперь используется: <code>{resolution}</code>"

            resolutions = {
                "1K": "Стандартное качество, 1024px",
                "2K": "HD качество, 2048px",
                "4K": "Максимальное качество, 4096px",
            }
            text += f"<i>{resolutions.get(resolution, '')}</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(
    F.data.startswith("img_ratio_") & ~F.data.startswith("img_ratio_no_preset")
)
async def handle_image_ratio_selection(
    callback: types.CallbackQuery, state: FSMContext
):
    """Обработка выбора формата изображения для пресетов"""
    parts = callback.data.split("_")
    if len(parts) >= 4:
        preset_id = parts[1]
        ratio = f"{parts[2]}:{parts[3]}"  # "16:9"

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["aspect_ratio"] = ratio
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            text = f"✅ <b>Формат изменён</b>"
            text += f"📐 Теперь используется: <code>{ratio}</code>"

            ratios_desc = {
                "1:1": "Квадрат (Instagram, Facebook)",
                "16:9": "Горизонтальный (YouTube)",
                "9:16": "Вертикальный (TikTok, Reels)",
                "4:5": "Портретный (Instagram)",
                "21:9": "Панорамный (Кино)",
            }
            text += f"<i>{ratios_desc.get(ratio, '')}</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("grounding_"))
async def handle_search_grounding(callback: types.CallbackQuery, state: FSMContext):
    """Обработка поискового заземления (Grounding)"""
    parts = callback.data.split("_")
    if len(parts) >= 2:
        preset_id = parts[1]

        # Переключаем опцию
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["enable_search"] = not generation_options.get(
            "enable_search", False
        )
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            enabled = generation_options["enable_search"]
            status = "🟢 ВКЛ" if enabled else "🔴 ВЫКЛ"
            text = f"✅ <b>Поиск в интернете: {status}</b>"

            if enabled:
                text += "<i>AI будет использовать Google Search для актуальной информации</i>\n"
                text += "\nПримеры:\n"
                text += "• Погода на 5 дней\n"
                text += "• Последние новости\n"
                text += "• Актуальные события"
            else:
                text += "<i>Поиск отключён</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("ref_"))
async def handle_reference_images(callback: types.CallbackQuery, state: FSMContext):
    """
    Обработка работы с референсными изображениями (до 14 шт)
    Поддерживает загрузку, управление и подтверждение референсов
    """
    parts = callback.data.split("_")
    action = parts[1] if len(parts) > 1 else ""
    preset_id = parts[2] if len(parts) > 2 else None

    data = await state.get_data()
    current_refs = data.get("reference_images", [])
    max_refs = 14

    if action == "upload":
        # Начинаем загрузку референсных изображений
        await state.set_state(GenerationStates.uploading_reference_images)
        await state.update_data(preset_id=preset_id, reference_images=current_refs)

        await callback.message.edit_text(
            f"📎 <b>Загрузка референсных изображений</b>"
            f"Загружено: <code>{len(current_refs)}/{max_refs}</code>"
            f"Отправьте фотографии (до {max_refs} штук), которые будут использоваться как референсы:\n"
            f"• До 10 объектов с высокой точностью\n"
            f"• До 4 персонажей для консистентности\n"
            f"• До 14 изображений суммарно"
            f"После загрузки нажмите ▶️ Продолжить",
            reply_markup=get_reference_images_upload_keyboard(
                len(current_refs), max_refs, preset_id
            ),
            parse_mode="HTML",
        )

    elif action == "clear":
        # Очищаем все референсы
        await state.update_data(reference_images=[])
        await callback.message.edit_text(
            f"📎 <b>Референсы очищены</b>"
            f"Загружено: <code>0/{max_refs}</code>"
            f"Отправьте фотографии для загрузки референсов:",
            reply_markup=get_reference_images_upload_keyboard(0, max_refs, preset_id),
            parse_mode="HTML",
        )

    elif action == "confirm":
        # Переходим к подтверждению
        if not current_refs:
            await callback.answer("❌ Нет загруженных изображений", show_alert=True)
            return

        # Для нового UX (preset_id == "new") - сразу переходим к выбору модели
        # (пропускаем экран подтверждения референсов)
        if preset_id == "new":
            data = await state.get_data()
            current_service = data.get("img_service", "banana_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>"
                f"Введите промпт для генерации:",
                reply_markup=get_create_image_keyboard(
                    current_service, current_ratio, num_refs=len(current_refs)
                ),
                parse_mode="HTML",
            )
            await callback.answer()
            await state.set_state(GenerationStates.waiting_for_input)
        else:
            # Для пресетов - сразу переходим к экрану пресета (пропускаем экран подтверждения)
            preset = preset_manager.get_preset(preset_id)
            if preset:
                await show_preset_details(
                    callback.message, preset, callback.from_user.id
                )
            else:
                # Fallback - показать параметры генерации
                data = await state.get_data()
                current_service = data.get("img_service", "banana_pro")
                current_ratio = data.get("img_ratio", "1:1")
                await callback.message.edit_text(
                    f"✨ <b>Создание фото</b>"
                    f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                    f"✨ Модель: <code>{current_service}</code>\n"
                    f"📐 Формат: <code>{current_ratio}</code>"
                    f"Введите промпт для генерации:",
                    reply_markup=get_create_image_keyboard(
                        current_service, current_ratio
                    ),
                    parse_mode="HTML",
                )
                await state.set_state(GenerationStates.waiting_for_input)

    elif action == "reload":
        # Перезагружаем — очищаем и начинаем заново
        await state.update_data(reference_images=[])
        await state.set_state(GenerationStates.uploading_reference_images)

        await callback.message.edit_text(
            f"📎 <b>Перезагрузка референсов</b>"
            f"Загружено: <code>0/{max_refs}</code>"
            f"Отправьте новые фотографии для загрузки референсов:",
            reply_markup=get_reference_images_upload_keyboard(0, max_refs, preset_id),
            parse_mode="HTML",
        )

    elif action == "accept":
        # Сохраняем референсы в generation_options
        generation_options = data.get("generation_options", {})
        generation_options["reference_images"] = current_refs
        await state.update_data(generation_options=generation_options)

        # Для нового UX (preset_id == "new") - переходим к экрану выбора модели/формата
        # (пропускаем промежуточное меню подтверждения)
        if preset_id == "new":
            current_service = data.get("img_service", "banana_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>"
                f"Введите промпт для генерации:",
                reply_markup=get_create_image_keyboard(current_service, current_ratio),
                parse_mode="HTML",
            )
            await state.set_state(GenerationStates.waiting_for_input)
        else:
            # Для пресетов - возвращаемся к экрану пресета
            preset = preset_manager.get_preset(preset_id)
            if preset:
                await show_preset_details(
                    callback.message, preset, callback.from_user.id
                )
            else:
                # Этот код не должен достигаться в нормальном потоке, но оставим для совместимости
                await callback.message.edit_text(
                    "✅ Референсы сохранены!",
                    reply_markup=get_back_keyboard("back_main"),
                )

    else:
        # Показываем справку о референсах (стандартное поведение)
        help_text = get_reference_images_help()

        await callback.message.edit_text(
            help_text,
            reply_markup=get_reference_images_keyboard(preset_id),
            parse_mode="HTML",
        )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.message(GenerationStates.waiting_for_input, F.photo)
async def process_photo_for_video_imgtxt(message: types.Message, state: FSMContext):
    """Обрабатывает загруженное фото для режима imgtxt (фото+текст → видео)"""
    data = await state.get_data()
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")

    # Проверяем, что это режим создания видео и выбран тип imgtxt
    if generation_type == "video" and v_type == "imgtxt":
        # Скачиваем изображение
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        image_bytes = await message.bot.download_file(file.file_path)
        image_data = image_bytes.read()

        # Validate image dimensions for video generation API
        try:
            import io

            from PIL import Image

            img = Image.open(io.BytesIO(image_data))
            width, height = img.size
            if width < 300 or height < 300:
                await message.answer(
                    f"❌ <b>Изображение слишком маленькое!</b>\\n\\n"
                    f"Размер: {width}×{height} px\\n\\n"
                    "Минимальный размер изображения: 300×300 px.\\n"
                    "Загрузите фото большего размера.",
                    parse_mode="HTML",
                    reply_markup=get_create_video_keyboard(
                        current_v_type=data.get("v_type", "imgtxt"),
                        current_model=data.get("v_model", "v26_pro"),
                        current_duration=data.get("v_duration", 5),
                        current_ratio=data.get("v_ratio", "16:9"),
                    ),
                )
                return
            logger.info(f"Image validated for Kling: {width}×{height}")
        except Exception as e:
            logger.error(f"Image validation failed: {e}")

        # Сохраняем изображение и получаем URL
        image_url = save_uploaded_file(image_data, "png", is_reference=True)

        if image_url:
            await state.update_data(v_image_url=image_url)
            logger.info(f"Saved start image for video: {image_url}")
        else:
            await message.answer(
                "❌ Не удалось сохранить изображение. Попробуйте ещё раз."
            )
            return

        # Получаем обновлённые данные
        data = await state.get_data()
        current_v_type = data.get("v_type", "imgtxt")
        current_model = data.get("v_model", "v26_pro")
        current_duration = data.get("v_duration", 5)
        current_ratio = data.get("v_ratio", "16:9")
        user_prompt = data.get("user_prompt", "")

        # Показываем подтверждение с обновлённым экраном
        image_status = "\n✅ <b>Изображение загружено!</b>\n"

        prompt_display = ""
        if user_prompt:
            prompt_display = f"\n📝 <b>Промпт:</b> <code>{user_prompt[:50]}{'...' if len(user_prompt) > 50 else ''}</code>\n"

        text = (
            f"🎬 <b>Создание видео</b>"
            f"{image_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Фото + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>"
            f"Опишите движение, которое хотите создать:\n"
            f"• Как двигается объект\n"
            f"• Движение камеры\n"
            f"• Стиль и атмосфера"
        )

        await message.answer(
            text,
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=current_model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )
        return

    # Если это не режим imgtxt - игнорируем (другие обработчики обработают)
    await message.answer("Пожалуйста, отправьте текстовое описание.")
    return


@router.message(
    GenerationStates.waiting_for_reference_video,
    F.video | (F.document & F.document.mime_type.startswith("video/")),
)
async def process_reference_video_upload(message: types.Message, state: FSMContext):
    """
    Обрабатывает загрузку референсного видео для режима video (видео+текст → видео).
    Сохраняет видео и переключает в состояние ожидания промпта.
    """
    data = await state.get_data()
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")

    if generation_type == "video" and v_type == "video":
        # Определяем источник файла (video или document)
        if message.video:
            video_obj = message.video
        elif message.document and message.document.mime_type.startswith("video/"):
            video_obj = message.document
        else:
            await message.answer("❌ Неверный тип файла. Отправьте видео.")
            return

        file = await message.bot.get_file(video_obj.file_id)

        # Проверяем размер (макс 20MB для стабильности)
        file_size = getattr(video_obj, "file_size", 0)
        if file_size > 20 * 1024 * 1024:
            await message.answer("❌ Видео слишком большое (макс 20MB).")
            return

        video_bytes = await message.bot.download_file(file.file_path)
        video_data = video_bytes.read()

        # Сохраняем видео и получаем URL
        video_url = save_uploaded_file(video_data, "mp4", is_reference=True)

        if video_url:
            v_reference_videos = data.get("v_reference_videos", [])
            if video_url not in v_reference_videos:
                v_reference_videos = [video_url, *v_reference_videos][:1]
            await state.update_data(
                v_video_url=video_url,
                v_reference_videos=v_reference_videos,
            )
            logger.info(f"Saved reference video for video mode: {video_url}")
        else:
            await message.answer("❌ Не удалось сохранить видео. Попробуйте ещё раз.")
            return

        # Переключаемся в состояние ожидания промпта
        await state.set_state(GenerationStates.waiting_for_video_prompt)

        # Получаем обновлённые данные
        data = await state.get_data()
        current_v_type = data.get("v_type", "video")
        current_model = data.get("v_model", "v26_pro")
        current_duration = data.get("v_duration", 5)
        current_ratio = data.get("v_ratio", "16:9")
        user_prompt = data.get("user_prompt", "")

        # Показываем экран с промптом
        video_status = "\n✅ <b>Референсное видео загружено!</b>\n"

        prompt_display = ""
        if user_prompt:
            prompt_display = f"\n📝 <b>Промпт:</b> <code>{user_prompt[:50]}{'...' if len(user_prompt) > 50 else ''}</code>\n"

        text = (
            f"🎬 <b>Создание видео</b>"
            f"{video_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Видео + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>"
            f"Опишите желаемый эффект/стиль:\n"
            f"• Стиль видео\n"
            f"• Дополнительные эффекты\n"
            f"• Атмосфера"
            f"<i>Видео будет использовано как референс для движения/стиля (@Video1)</i>"
        )

        await message.answer(
            text,
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=current_model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )
        return

    await message.answer("Пожалуйста, отправьте текстовое описание.")


@router.message(GenerationStates.waiting_for_reference_video)
async def invalid_reference_video_input(message: types.Message, state: FSMContext):
    """
    Обрабатывает невалидный ввод в состоянии waiting_for_reference_video.
    """
    await message.answer(
        "⚠️ Пожалуйста, отправьте видео файл (макс 50MB)."
        "Это видео будет использовано как референс для стиля/движения."
    )


@router.message(GenerationStates.waiting_for_video_prompt, F.text)
async def handle_video_prompt_text(message: types.Message, state: FSMContext):
    """Обрабатывает ввод промпта для видео и motion control (новый UX)."""
    logger.info(f"[DEBUG STATE] Current state: {await state.get_state()}")
    logger.info(f"Video prompt handler triggered for user {message.from_user.id}")
    prompt = message.text.strip()

    if not prompt:
        await message.answer("⚠️ Введите описание видео перед запуском генерации.")
        return

    data = await state.get_data()
    generation_type = data.get("generation_type", "")
    logger.info(f"Generation type: {generation_type}")

    await state.update_data(user_prompt=prompt)

    if generation_type == "motion_control":
        logger.info("Calling run_motion_control")
        await run_motion_control(message, state, prompt)
    else:
        logger.info("Calling run_no_preset_video_from_message")
        await run_no_preset_video_from_message(message, state, prompt)


# =============================================================================
# ОБРАБОТЧИКИ ОПЦИЙ ГЕНЕРАЦИИ (НОВОЕ СОГЛАСНО banana_api.md)
# =============================================================================


@router.callback_query(F.data.startswith("model_"))
async def handle_model_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора модели генерации"""
    parts = callback.data.split("_")
    if len(parts) >= 3:
        preset_id = parts[1]
        model_type = parts[2]  # "flash" или "pro"

        model = (
            "gemini-2.5-flash-image"
            if model_type == "flash"
            else "gemini-3-pro-image-preview"
        )

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["model"] = model
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            model_emoji = "💎" if "pro" in model else "⚡"
            text = f"✅ <b>Модель изменена</b>"
            text += f"{model_emoji} Теперь используется: <code>{model}</code>"

            if model_type == "flash":
                text += "<i>Быстрая генерация, до 1024px</i>\n"
            else:
                text += "<i>Высокое качество, до 4K, с thinking</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("resolution_"))
async def handle_resolution_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора разрешения изображения"""
    parts = callback.data.split("_")
    if len(parts) >= 3:
        preset_id = parts[1]
        resolution = parts[2]  # "1K", "2K", "4K"

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["resolution"] = resolution
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            res_emoji = {"1K": "⚡", "2K": "💎", "4K": "👑"}.get(resolution, "⚡")
            text = f"✅ <b>Разрешение изменено</b>"
            text += f"{res_emoji} Теперь используется: <code>{resolution}</code>"

            resolutions = {
                "1K": "Стандартное качество, 1024px",
                "2K": "HD качество, 2048px",
                "4K": "Максимальное качество, 4096px",
            }
            text += f"<i>{resolutions.get(resolution, '')}</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(
    F.data.startswith("img_ratio_") & ~F.data.startswith("img_ratio_no_preset")
)
async def handle_image_ratio_selection(
    callback: types.CallbackQuery, state: FSMContext
):
    """Обработка выбора формата изображения для пресетов"""
    parts = callback.data.split("_")
    if len(parts) >= 4:
        preset_id = parts[1]
        ratio = f"{parts[2]}:{parts[3]}"  # "16:9"

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["aspect_ratio"] = ratio
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            text = f"✅ <b>Формат изменён</b>"
            text += f"📐 Теперь используется: <code>{ratio}</code>"

            ratios_desc = {
                "1:1": "Квадрат (Instagram, Facebook)",
                "16:9": "Горизонтальный (YouTube)",
                "9:16": "Вертикальный (TikTok, Reels)",
                "4:5": "Портретный (Instagram)",
                "21:9": "Панорамный (Кино)",
            }
            text += f"<i>{ratios_desc.get(ratio, '')}</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("grounding_"))
async def handle_search_grounding(callback: types.CallbackQuery, state: FSMContext):
    """Обработка поискового заземления (Grounding)"""
    parts = callback.data.split("_")
    if len(parts) >= 2:
        preset_id = parts[1]

        # Переключаем опцию
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["enable_search"] = not generation_options.get(
            "enable_search", False
        )
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            enabled = generation_options["enable_search"]
            status = "🟢 ВКЛ" if enabled else "🔴 ВЫКЛ"
            text = f"✅ <b>Поиск в интернете: {status}</b>"

            if enabled:
                text += "<i>AI будет использовать Google Search для актуальной информации</i>\n"
                text += "\nПримеры:\n"
                text += "• Погода на 5 дней\n"
                text += "• Последние новости\n"
                text += "• Актуальные события"
            else:
                text += "<i>Поиск отключён</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("ref_"))
async def handle_reference_images(callback: types.CallbackQuery, state: FSMContext):
    """
    Обработка работы с референсными изображениями (до 14 шт)
    Поддерживает загрузку, управление и подтверждение референсов
    """
    parts = callback.data.split("_")
    action = parts[1] if len(parts) > 1 else ""
    preset_id = parts[2] if len(parts) > 2 else None

    data = await state.get_data()
    current_refs = data.get("reference_images", [])
    max_refs = 14

    if action == "upload":
        # Начинаем загрузку референсных изображений
        await state.set_state(GenerationStates.uploading_reference_images)
        await state.update_data(preset_id=preset_id, reference_images=current_refs)

        await callback.message.edit_text(
            f"📎 <b>Загрузка референсных изображений</b>"
            f"Загружено: <code>{len(current_refs)}/{max_refs}</code>"
            f"Отправьте фотографии (до {max_refs} штук), которые будут использоваться как референсы:\n"
            f"• До 10 объектов с высокой точностью\n"
            f"• До 4 персонажей для консистентности\n"
            f"• До 14 изображений суммарно"
            f"После загрузки нажмите ▶️ Продолжить",
            reply_markup=get_reference_images_upload_keyboard(
                len(current_refs), max_refs, preset_id
            ),
            parse_mode="HTML",
        )

    elif action == "clear":
        # Очищаем все референсы
        await state.update_data(reference_images=[])
        await callback.message.edit_text(
            f"📎 <b>Референсы очищены</b>"
            f"Загружено: <code>0/{max_refs}</code>"
            f"Отправьте фотографии для загрузки референсов:",
            reply_markup=get_reference_images_upload_keyboard(0, max_refs, preset_id),
            parse_mode="HTML",
        )

    elif action == "confirm":
        # Переходим к подтверждению
        if not current_refs:
            await callback.answer("❌ Нет загруженных изображений", show_alert=True)
            return

        # Для нового UX (preset_id == "new") - сразу переходим к выбору модели
        # (пропускаем экран подтверждения референсов)
        if preset_id == "new":
            data = await state.get_data()
            current_service = data.get("img_service", "banana_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>"
                f"Введите промпт для генерации:",
                reply_markup=get_create_image_keyboard(
                    current_service, current_ratio, num_refs=len(current_refs)
                ),
                parse_mode="HTML",
            )
            await callback.answer()
            await state.set_state(GenerationStates.waiting_for_input)
        else:
            # Для пресетов - сразу переходим к экрану пресета (пропускаем экран подтверждения)
            preset = preset_manager.get_preset(preset_id)
            if preset:
                await show_preset_details(
                    callback.message, preset, callback.from_user.id
                )
            else:
                # Fallback - показать параметры генерации
                data = await state.get_data()
                current_service = data.get("img_service", "banana_pro")
                current_ratio = data.get("img_ratio", "1:1")
                await callback.message.edit_text(
                    f"✨ <b>Создание фото</b>"
                    f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                    f"✨ Модель: <code>{current_service}</code>\n"
                    f"📐 Формат: <code>{current_ratio}</code>"
                    f"Введите промпт для генерации:",
                    reply_markup=get_create_image_keyboard(
                        current_service, current_ratio
                    ),
                    parse_mode="HTML",
                )
                await state.set_state(GenerationStates.waiting_for_input)

    elif action == "reload":
        # Перезагружаем — очищаем и начинаем заново
        await state.update_data(reference_images=[])
        await state.set_state(GenerationStates.uploading_reference_images)

        await callback.message.edit_text(
            f"📎 <b>Перезагрузка референсов</b>"
            f"Загружено: <code>0/{max_refs}</code>"
            f"Отправьте новые фотографии для загрузки референсов:",
            reply_markup=get_reference_images_upload_keyboard(0, max_refs, preset_id),
            parse_mode="HTML",
        )

    elif action == "accept":
        # Сохраняем референсы в generation_options
        generation_options = data.get("generation_options", {})
        generation_options["reference_images"] = current_refs
        await state.update_data(generation_options=generation_options)

        # Для нового UX (preset_id == "new") - переходим к экрану выбора модели/формата
        # (пропускаем промежуточное меню подтверждения)
        if preset_id == "new":
            current_service = data.get("img_service", "banana_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>"
                f"Введите промпт для генерации:",
                reply_markup=get_create_image_keyboard(current_service, current_ratio),
                parse_mode="HTML",
            )
            await state.set_state(GenerationStates.waiting_for_input)
        else:
            # Для пресетов - возвращаемся к экрану пресета
            preset = preset_manager.get_preset(preset_id)
            if preset:
                await show_preset_details(
                    callback.message, preset, callback.from_user.id
                )
            else:
                # Этот код не должен достигаться в нормальном потоке, но оставим для совместимости
                await callback.message.edit_text(
                    "✅ Референсы сохранены!",
                    reply_markup=get_back_keyboard("back_main"),
                )

    else:
        # Показываем справку о референсах (стандартное поведение)
        help_text = get_reference_images_help()

        await callback.message.edit_text(
            help_text,
            reply_markup=get_reference_images_keyboard(preset_id),
            parse_mode="HTML",
        )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.message(
    GenerationStates.waiting_for_reference_video,
    F.video | (F.document & F.document.mime_type.startswith("video/")),
)
async def process_reference_video_upload(message: types.Message, state: FSMContext):
    """
    Обрабатывает загрузку референсного видео для режима video (видео+текст → видео).
    Сохраняет видео и переключает в состояние ожидания промпта.
    """
    data = await state.get_data()
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")

    if generation_type == "video" and v_type == "video":
        # Определяем источник файла (video или document)
        if message.video:
            video_obj = message.video
        elif message.document and message.document.mime_type.startswith("video/"):
            video_obj = message.document
        else:
            await message.answer("❌ Неверный тип файла. Отправьте видео.")
            return

        file = await message.bot.get_file(video_obj.file_id)

        # Проверяем размер (макс 20MB для стабильности)
        file_size = getattr(video_obj, "file_size", 0)
        if file_size > 20 * 1024 * 1024:
            await message.answer("❌ Видео слишком большое (макс 20MB).")
            return

        video_bytes = await message.bot.download_file(file.file_path)
        video_data = video_bytes.read()

        # Сохраняем видео и получаем URL
        video_url = save_uploaded_file(video_data, "mp4", is_reference=True)

        if video_url:
            v_reference_videos = data.get("v_reference_videos", [])
            if video_url not in v_reference_videos:
                v_reference_videos = [video_url, *v_reference_videos][:1]
            await state.update_data(
                v_video_url=video_url,
                v_reference_videos=v_reference_videos,
            )
            logger.info(f"Saved reference video for video mode: {video_url}")
        else:
            await message.answer("❌ Не удалось сохранить видео. Попробуйте ещё раз.")
            return

        # Переключаемся в состояние ожидания промпта
        await state.set_state(GenerationStates.waiting_for_video_prompt)

        # Получаем обновлённые данные
        data = await state.get_data()
        current_v_type = data.get("v_type", "video")
        current_model = data.get("v_model", "v26_pro")
        current_duration = data.get("v_duration", 5)
        current_ratio = data.get("v_ratio", "16:9")
        user_prompt = data.get("user_prompt", "")

        # Показываем экран с промптом
        video_status = "\n✅ <b>Референсное видео загружено!</b>\n"

        prompt_display = ""
        if user_prompt:
            prompt_display = f"\n📝 <b>Промпт:</b> <code>{user_prompt[:50]}{'...' if len(user_prompt) > 50 else ''}</code>\n"

        text = (
            f"🎬 <b>Создание видео</b>"
            f"{video_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Видео + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>"
            f"Опишите желаемый эффект/стиль:\n"
            f"• Стиль видео\n"
            f"• Дополнительные эффекты\n"
            f"• Атмосфера"
            f"<i>Видео будет использовано как референс для движения/стиля (@Video1)</i>"
        )

        await message.answer(
            text,
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=current_model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )
        return

    await message.answer("Пожалуйста, отправьте текстовое описание.")


@router.message(GenerationStates.waiting_for_reference_video)
async def invalid_reference_video_input(message: types.Message, state: FSMContext):
    """
    Обрабатывает невалидный ввод в состоянии waiting_for_reference_video.
    """
    await message.answer(
        "⚠️ Пожалуйста, отправьте видео файл (макс 50MB)."
        "Это видео будет использовано как референс для стиля/движения."
    )


@router.message(GenerationStates.waiting_for_video_prompt, F.text)
async def handle_video_prompt_text(message: types.Message, state: FSMContext):
    """Обрабатывает ввод промпта для видео и motion control (новый UX)."""
    logger.info(f"[DEBUG STATE] Current state: {await state.get_state()}")
    logger.info(f"Video prompt handler triggered for user {message.from_user.id}")
    prompt = message.text.strip()

    if not prompt:
        await message.answer("⚠️ Введите описание видео перед запуском генерации.")
        return

    data = await state.get_data()
    generation_type = data.get("generation_type", "")
    logger.info(f"Generation type: {generation_type}")

    await state.update_data(user_prompt=prompt)

    if generation_type == "motion_control":
        logger.info("Calling run_motion_control")
        await run_motion_control(message, state, prompt)
    else:
        logger.info("Calling run_no_preset_video_from_message")
        await run_no_preset_video_from_message(message, state, prompt)


# =============================================================================
# ОБРАБОТЧИКИ ОПЦИЙ ГЕНЕРАЦИИ (НОВОЕ СОГЛАСНО banana_api.md)
# =============================================================================


@router.callback_query(F.data.startswith("model_"))
async def handle_model_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора модели генерации"""
    parts = callback.data.split("_")
    if len(parts) >= 3:
        preset_id = parts[1]
        model_type = parts[2]  # "flash" или "pro"

        model = (
            "gemini-2.5-flash-image"
            if model_type == "flash"
            else "gemini-3-pro-image-preview"
        )

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["model"] = model
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            model_emoji = "💎" if "pro" in model else "⚡"
            text = f"✅ <b>Модель изменена</b>"
            text += f"{model_emoji} Теперь используется: <code>{model}</code>"

            if model_type == "flash":
                text += "<i>Быстрая генерация, до 1024px</i>\n"
            else:
                text += "<i>Высокое качество, до 4K, с thinking</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("resolution_"))
async def handle_resolution_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора разрешения изображения"""
    parts = callback.data.split("_")
    if len(parts) >= 3:
        preset_id = parts[1]
        resolution = parts[2]  # "1K", "2K", "4K"

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["resolution"] = resolution
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            res_emoji = {"1K": "⚡", "2K": "💎", "4K": "👑"}.get(resolution, "⚡")
            text = f"✅ <b>Разрешение изменено</b>"
            text += f"{res_emoji} Теперь используется: <code>{resolution}</code>"

            resolutions = {
                "1K": "Стандартное качество, 1024px",
                "2K": "HD качество, 2048px",
                "4K": "Максимальное качество, 4096px",
            }
            text += f"<i>{resolutions.get(resolution, '')}</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(
    F.data.startswith("img_ratio_") & ~F.data.startswith("img_ratio_no_preset")
)
async def handle_image_ratio_selection(
    callback: types.CallbackQuery, state: FSMContext
):
    """Обработка выбора формата изображения для пресетов"""
    parts = callback.data.split("_")
    if len(parts) >= 4:
        preset_id = parts[1]
        ratio = f"{parts[2]}:{parts[3]}"  # "16:9"

        # Обновляем опции
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["aspect_ratio"] = ratio
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            text = f"✅ <b>Формат изменён</b>"
            text += f"📐 Теперь используется: <code>{ratio}</code>"

            ratios_desc = {
                "1:1": "Квадрат (Instagram, Facebook)",
                "16:9": "Горизонтальный (YouTube)",
                "9:16": "Вертикальный (TikTok, Reels)",
                "4:5": "Портретный (Instagram)",
                "21:9": "Панорамный (Кино)",
            }
            text += f"<i>{ratios_desc.get(ratio, '')}</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("grounding_"))
async def handle_search_grounding(callback: types.CallbackQuery, state: FSMContext):
    """Обработка поискового заземления (Grounding)"""
    parts = callback.data.split("_")
    if len(parts) >= 2:
        preset_id = parts[1]

        # Переключаем опцию
        data = await state.get_data()
        generation_options = data.get("generation_options", {})
        generation_options["enable_search"] = not generation_options.get(
            "enable_search", False
        )
        await state.update_data(generation_options=generation_options)

        # Показываем подтверждение
        preset = preset_manager.get_preset(preset_id)
        if preset:
            enabled = generation_options["enable_search"]
            status = "🟢 ВКЛ" if enabled else "🔴 ВЫКЛ"
            text = f"✅ <b>Поиск в интернете: {status}</b>"

            if enabled:
                text += "<i>AI будет использовать Google Search для актуальной информации</i>\n"
                text += "\nПримеры:\n"
                text += "• Погода на 5 дней\n"
                text += "• Последние новости\n"
                text += "• Актуальные события"
            else:
                text += "<i>Поиск отключён</i>\n"

            await callback.message.edit_text(
                text,
                reply_markup=get_preset_action_keyboard(
                    preset_id, preset.requires_input, preset.category
                ),
                parse_mode="HTML",
            )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.callback_query(F.data.startswith("ref_"))
async def handle_reference_images(callback: types.CallbackQuery, state: FSMContext):
    """
    Обработка работы с референсными изображениями (до 14 шт)
    Поддерживает загрузку, управление и подтверждение референсов
    """
    parts = callback.data.split("_")
    action = parts[1] if len(parts) > 1 else ""
    preset_id = parts[2] if len(parts) > 2 else None

    data = await state.get_data()
    current_refs = data.get("reference_images", [])
    max_refs = 14

    if action == "upload":
        # Начинаем загрузку референсных изображений
        await state.set_state(GenerationStates.uploading_reference_images)
        await state.update_data(preset_id=preset_id, reference_images=current_refs)

        await callback.message.edit_text(
            f"📎 <b>Загрузка референсных изображений</b>"
            f"Загружено: <code>{len(current_refs)}/{max_refs}</code>"
            f"Отправьте фотографии (до {max_refs} штук), которые будут использоваться как референсы:\n"
            f"• До 10 объектов с высокой точностью\n"
            f"• До 4 персонажей для консистентности\n"
            f"• До 14 изображений суммарно"
            f"После загрузки нажмите ▶️ Продолжить",
            reply_markup=get_reference_images_upload_keyboard(
                len(current_refs), max_refs, preset_id
            ),
            parse_mode="HTML",
        )

    elif action == "clear":
        # Очищаем все референсы
        await state.update_data(reference_images=[])
        await callback.message.edit_text(
            f"📎 <b>Референсы очищены</b>"
            f"Загружено: <code>0/{max_refs}</code>"
            f"Отправьте фотографии для загрузки референсов:",
            reply_markup=get_reference_images_upload_keyboard(0, max_refs, preset_id),
            parse_mode="HTML",
        )

    elif action == "confirm":
        # Переходим к подтверждению
        if not current_refs:
            await callback.answer("❌ Нет загруженных изображений", show_alert=True)
            return

        # Для нового UX (preset_id == "new") - сразу переходим к выбору модели
        # (пропускаем экран подтверждения референсов)
        if preset_id == "new":
            data = await state.get_data()
            current_service = data.get("img_service", "banana_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>"
                f"Введите промпт для генерации:",
                reply_markup=get_create_image_keyboard(
                    current_service, current_ratio, num_refs=len(current_refs)
                ),
                parse_mode="HTML",
            )
            await callback.answer()
            await state.set_state(GenerationStates.waiting_for_input)
        else:
            # Для пресетов - сразу переходим к экрану пресета (пропускаем экран подтверждения)
            preset = preset_manager.get_preset(preset_id)
            if preset:
                await show_preset_details(
                    callback.message, preset, callback.from_user.id
                )
            else:
                # Fallback - показать параметры генерации
                data = await state.get_data()
                current_service = data.get("img_service", "banana_pro")
                current_ratio = data.get("img_ratio", "1:1")
                await callback.message.edit_text(
                    f"✨ <b>Создание фото</b>"
                    f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                    f"✨ Модель: <code>{current_service}</code>\n"
                    f"📐 Формат: <code>{current_ratio}</code>"
                    f"Введите промпт для генерации:",
                    reply_markup=get_create_image_keyboard(
                        current_service, current_ratio
                    ),
                    parse_mode="HTML",
                )
                await state.set_state(GenerationStates.waiting_for_input)

    elif action == "reload":
        # Перезагружаем — очищаем и начинаем заново
        await state.update_data(reference_images=[])
        await state.set_state(GenerationStates.uploading_reference_images)

        await callback.message.edit_text(
            f"📎 <b>Перезагрузка референсов</b>"
            f"Загружено: <code>0/{max_refs}</code>"
            f"Отправьте новые фотографии для загрузки референсов:",
            reply_markup=get_reference_images_upload_keyboard(0, max_refs, preset_id),
            parse_mode="HTML",
        )

    elif action == "accept":
        # Сохраняем референсы в generation_options
        generation_options = data.get("generation_options", {})
        generation_options["reference_images"] = current_refs
        await state.update_data(generation_options=generation_options)

        # Для нового UX (preset_id == "new") - переходим к экрану выбора модели/формата
        # (пропускаем промежуточное меню подтверждения)
        if preset_id == "new":
            current_service = data.get("img_service", "banana_pro")
            current_ratio = data.get("img_ratio", "1:1")
            await callback.message.edit_text(
                f"✨ <b>Создание фото</b>"
                f"📎 Референсы загружены: <code>{len(current_refs)}</code>"
                f"✨ Модель: <code>{current_service}</code>\n"
                f"📐 Формат: <code>{current_ratio}</code>"
                f"Введите промпт для генерации:",
                reply_markup=get_create_image_keyboard(current_service, current_ratio),
                parse_mode="HTML",
            )
            await state.set_state(GenerationStates.waiting_for_input)
        else:
            # Для пресетов - возвращаемся к экрану пресета
            preset = preset_manager.get_preset(preset_id)
            if preset:
                await show_preset_details(
                    callback.message, preset, callback.from_user.id
                )
            else:
                # Этот код не должен достигаться в нормальном потоке, но оставим для совместимости
                await callback.message.edit_text(
                    "✅ Референсы сохранены!",
                    reply_markup=get_back_keyboard("back_main"),
                )

    else:
        # Показываем справку о референсах (стандартное поведение)
        help_text = get_reference_images_help()

        await callback.message.edit_text(
            help_text,
            reply_markup=get_reference_images_keyboard(preset_id),
            parse_mode="HTML",
        )

    await callback.answer()
    await state.set_state(GenerationStates.waiting_for_input)


@router.message(
    GenerationStates.waiting_for_reference_video,
    F.video | (F.document & F.document.mime_type.startswith("video/")),
)
async def process_reference_video_upload(message: types.Message, state: FSMContext):
    """
    Обрабатывает загрузку референсного видео для режима video (видео+текст → видео).
    Сохраняет видео и переключает в состояние ожидания промпта.
    """
    data = await state.get_data()
    generation_type = data.get("generation_type")
    v_type = data.get("v_type")

    if generation_type == "video" and v_type == "video":
        # Определяем источник файла (video или document)
        if message.video:
            video_obj = message.video
        elif message.document and message.document.mime_type.startswith("video/"):
            video_obj = message.document
        else:
            await message.answer("❌ Неверный тип файла. Отправьте видео.")
            return

        file = await message.bot.get_file(video_obj.file_id)

        # Проверяем размер (макс 20MB для стабильности)
        file_size = getattr(video_obj, "file_size", 0)
        if file_size > 20 * 1024 * 1024:
            await message.answer("❌ Видео слишком большое (макс 20MB).")
            return

        video_bytes = await message.bot.download_file(file.file_path)
        video_data = video_bytes.read()

        # Сохраняем видео и получаем URL
        video_url = save_uploaded_file(video_data, "mp4", is_reference=True)

        if video_url:
            v_reference_videos = data.get("v_reference_videos", [])
            if video_url not in v_reference_videos:
                v_reference_videos = [video_url, *v_reference_videos][:1]
            await state.update_data(
                v_video_url=video_url,
                v_reference_videos=v_reference_videos,
            )
            logger.info(f"Saved reference video for video mode: {video_url}")
        else:
            await message.answer("❌ Не удалось сохранить видео. Попробуйте ещё раз.")
            return

        # Переключаемся в состояние ожидания промпта
        await state.set_state(GenerationStates.waiting_for_video_prompt)

        # Получаем обновлённые данные
        data = await state.get_data()
        current_v_type = data.get("v_type", "video")
        current_model = data.get("v_model", "v26_pro")
        current_duration = data.get("v_duration", 5)
        current_ratio = data.get("v_ratio", "16:9")
        user_prompt = data.get("user_prompt", "")

        # Показываем экран с промптом
        video_status = "\n✅ <b>Референсное видео загружено!</b>\n"

        prompt_display = ""
        if user_prompt:
            prompt_display = f"\n📝 <b>Промпт:</b> <code>{user_prompt[:50]}{'...' if len(user_prompt) > 50 else ''}</code>\n"

        text = (
            f"🎬 <b>Создание видео</b>"
            f"{video_status}"
            f"⚙️ <b>Текущие настройки:</b>\n"
            f"   📝 Тип: <code>Видео + Текст → Видео</code>\n"
            f"   🤖 Модель: <code>{current_model}</code>\n"
            f"   ⏱ Длительность: <code>{current_duration} сек</code>\n"
            f"   📐 Формат: <code>{current_ratio}</code>\n"
            f"{prompt_display}\n"
            f"<b>Введите промпт для генерации:</b>"
            f"Опишите желаемый эффект/стиль:\n"
            f"• Стиль видео\n"
            f"• Дополнительные эффекты\n"
            f"• Атмосфера"
            f"<i>Видео будет использовано как референс для движения/стиля (@Video1)</i>"
        )

        await message.answer(
            text,
            reply_markup=get_create_video_keyboard(
                current_v_type=current_v_type,
                current_model=current_model,
                current_duration=current_duration,
                current_ratio=current_ratio,
            ),
            parse_mode="HTML",
        )
        return

    await message.answer("Пожалуйста, отправьте текстовое описание.")


@router.message(GenerationStates.waiting_for_reference_video)
async def invalid_reference_video_input(message: types.Message, state: FSMContext):
    """
    Обрабатывает невалидный ввод в состоянии waiting_for_reference_video.
    """
    await message.answer(
        "⚠️ Пожалуйста, отправьте видео файл (макс 50MB).\\n\\n"
        "Это видео будет использовано как референс для стиля/движения."
    )
