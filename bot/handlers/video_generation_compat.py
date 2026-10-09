from __future__ import annotations

import json
import logging

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.creator_tariff import quote_video_for_actor
from bot.database import (
    add_credits,
    check_can_afford,
    deduct_credits,
    get_or_create_user,
    get_task_by_id,
)
from bot.handlers.generation import (
    _GROK_VIDEO_MODELS,
    _show_video_creation_screen,
    run_no_preset_video_from_callback,
)
from bot.keyboards import get_video_model_label
from bot.model_capabilities import (
    VIDEO_MODEL_CAPABILITIES,
    get_video_capability,
    normalize_video_model_key,
)
from bot.video_generation_contract import build_repeat_video_state

logger = logging.getLogger(__name__)
router = Router()

PUBLIC_VIDEO_MODEL_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Kling", ("v3_std", "v3_pro", "v3_4k", "v26_pro")),
    ("Motion и Avatar", ("motion_control_v26", "motion_control_v30", "glow", "avatar_std", "avatar_pro")),
    ("Seedance и Grok", ("seedance_2_5", "seedance_2", "grok_imagine", "grok_imagine_v15")),
    ("Veo", ("veo3", "veo3_fast", "veo3_lite")),
    ("Gemini Omni", ("gemini_omni_video", "gemini_omni_audio", "gemini_omni_character")),
)

MODEL_EMOJI = {
    "v3_std": "⚡", "v3_pro": "💎", "v3_4k": "🖥", "v26_pro": "🌀",
    "motion_control_v26": "🎯", "motion_control_v30": "🚀", "glow": "✨",
    "avatar_std": "🗣", "avatar_pro": "🎙", "seedance_2_5": "🆕", "seedance_2": "🎞",
    "seedance_2_fast": "⚡", "grok_imagine": "🧠", "grok_imagine_v15": "🔥",
    "veo3": "🎥", "veo3_fast": "🚄", "veo3_lite": "🌿",
    "gemini_omni_video": "🔷", "gemini_omni_audio": "🎧", "gemini_omni_character": "🧍",
}


# Family tabs are presentation only; every existing public model remains reachable.
VIDEO_MODEL_FAMILIES = (
    ("all", "Все", tuple(key for _, keys in PUBLIC_VIDEO_MODEL_GROUPS for key in keys) + ("wan_3_prime",)),
    ("wan", "Wan", ("wan_3_prime",)),
    ("kling", "Kling", PUBLIC_VIDEO_MODEL_GROUPS[0][1]),
    ("motion", "Motion / Аватары", PUBLIC_VIDEO_MODEL_GROUPS[1][1]),
    ("seedance", "Seedance", ("seedance_2_5", "seedance_2")),
    ("grok", "Grok", ("grok_imagine", "grok_imagine_v15")),
    ("veo", "Veo", PUBLIC_VIDEO_MODEL_GROUPS[3][1]),
    ("gemini", "Gemini", PUBLIC_VIDEO_MODEL_GROUPS[4][1]),
)
VIDEO_MODEL_PAGE_SIZE = 6


def _video_model_page(family: str = "all", page: int = 0):
    groups = {key: models for key, _label, models in VIDEO_MODEL_FAMILIES}
    if family not in groups:
        family = "all"
    models = tuple(key for key in groups[family] if key in VIDEO_MODEL_CAPABILITIES)
    pages = max(1, (len(models) + VIDEO_MODEL_PAGE_SIZE - 1) // VIDEO_MODEL_PAGE_SIZE)
    try:
        page = max(0, min(int(page), pages - 1))
    except (TypeError, ValueError):
        page = 0
    start = page * VIDEO_MODEL_PAGE_SIZE
    return family, page, pages, models[start:start + VIDEO_MODEL_PAGE_SIZE]


def _advanced_video_models_keyboard(
    current_model: str | None = None, *, family: str = "all", page: int = 0,
) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    selected = normalize_video_model_key(current_model)
    family, page, pages, model_keys = _video_model_page(family, page)
    tabs = [types.InlineKeyboardButton(
        text=("• " if key == family else "") + label,
        callback_data=f"video_models:{key}:0",
    ) for key, label, _models in VIDEO_MODEL_FAMILIES]
    for offset in range(0, len(tabs), 3):
        builder.row(*tabs[offset:offset + 3])
    for model_key in model_keys:
        capability = VIDEO_MODEL_CAPABILITIES[model_key]
        prefix = "✅ " if selected == model_key else ""
        callback_data = (
            f"v_model_{model_key}" if model_key in {"seedance_2_5", "wan_3_prime"}
            else f"advanced_v_model_{model_key}"
        )
        builder.row(types.InlineKeyboardButton(
            text=f"{prefix}{MODEL_EMOJI.get(model_key, '🎬')} {capability.label}",
            callback_data=callback_data,
        ))
    if pages > 1:
        navigation = []
        if page > 0:
            navigation.append(types.InlineKeyboardButton(text="‹ Назад", callback_data=f"video_models:{family}:{page - 1}"))
        navigation.append(types.InlineKeyboardButton(text=f"{page + 1} / {pages}", callback_data=f"video_models:{family}:{page}"))
        if page + 1 < pages:
            navigation.append(types.InlineKeyboardButton(text="Далее ›", callback_data=f"video_models:{family}:{page + 1}"))
        builder.row(*navigation)
    builder.row(types.InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main"))
    return builder.as_markup()


async def _render_video_model_page(callback, state, *, family="all", page=0, current_model=None):
    family, page, pages, _models = _video_model_page(family, page)
    await state.update_data(video_model_family=family, video_model_page=page, video_flow_step="select_model")
    text = (
        "🎬 <b>Создание видео</b>\n<b>Шаг 1. Выберите модель</b>\n\n"
        "Выберите семейство или листайте общий каталог. Все режимы сохранены."
    )
    markup = _advanced_video_models_keyboard(current_model, family=family, page=page)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            await callback.message.answer(text, parse_mode="HTML", reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("video_models:"))
async def show_video_models_page(callback: types.CallbackQuery, state: FSMContext) -> None:
    parts = str(callback.data or "").split(":")
    data = await state.get_data()
    await _render_video_model_page(
        callback, state, family=parts[1] if len(parts) > 1 else "all",
        page=parts[2] if len(parts) > 2 else 0, current_model=data.get("v_model", "v3_pro"),
    )


def _initial_type_for_model(model: str) -> str:
    if model in _GROK_VIDEO_MODELS or model == "seedance_2":
        return "imgtxt"
    if model in {"motion_control_v26", "motion_control_v30", "glow"}:
        return "motion"
    if model in {"avatar_std", "avatar_pro"}:
        return "avatar"
    if model == "gemini_omni_audio":
        return "audio"
    if model == "gemini_omni_character":
        return "character"
    return "text"


@router.callback_query(F.data.in_({"create_video_new", "video_change_model"}))
async def show_complete_video_model_selection(callback: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if callback.data == "create_video_new":
        await state.clear()
        await state.update_data(
            generation_type="video",
            video_flow_step="select_model",
            v_model="v3_pro",
            v_type="text",
            v_duration=5,
            v_ratio="16:9",
            v_mode="720p",
            reference_images=[],
            v_reference_videos=[],
            v_reference_audio=[],
        )
        current_model = "v3_pro"
    else:
        await state.update_data(video_flow_step="select_model")
        current_model = data.get("v_model", "v3_pro")

    await _render_video_model_page(
        callback, state, current_model=current_model,
        family="all" if callback.data == "create_video_new" else data.get("video_model_family", "all"),
        page=0 if callback.data == "create_video_new" else data.get("video_model_page", 0),
    )


@router.callback_query(F.data.startswith("advanced_v_model_"))
async def select_advanced_video_model(callback: types.CallbackQuery, state: FSMContext) -> None:
    model = normalize_video_model_key(
        str(callback.data or "").replace("advanced_v_model_", "", 1)
    )
    capability = get_video_capability(model)
    if capability is None:
        await callback.answer("Эта модель пока недоступна.", show_alert=True)
        return

    duration = capability.durations[0] if capability.durations else 5
    ratio = capability.aspect_ratios[0] if capability.aspect_ratios else "16:9"
    resolution = capability.resolutions[0] if capability.resolutions else "720p"
    await state.update_data(
        generation_type="video",
        video_flow_step="configure",
        v_model=model,
        v_type=_initial_type_for_model(model),
        v_duration=duration,
        v_ratio=ratio,
        v_mode=resolution,
        motion_quality=resolution,
        reference_images=[],
        v_reference_videos=[],
        v_reference_audio=[],
        v_image_url=None,
        v_end_image_url=None,
        avatar_audio_url=None,
    )
    await _show_video_creation_screen(callback, state)
    await callback.answer(f"Выбрано: {capability.label}")


@router.callback_query(F.data.startswith("repeat_video_result_"))
async def repeat_advanced_video_result(callback: types.CallbackQuery, state: FSMContext) -> None:
    task_id = str(callback.data or "").replace("repeat_video_result_", "", 1)
    task = await get_task_by_id(task_id)
    if not task or task.type != "video":
        await callback.answer("Не удалось найти данные для повтора.", show_alert=True)
        return

    from bot.genjutsu.feed import redirect_legacy_repeat

    if await redirect_legacy_repeat(callback, task):
        return

    from bot.handlers.miniapp_video_continuity_compat import redirect_typed_video_repeat

    if await redirect_typed_video_repeat(callback, task):
        return

    try:
        request_data = json.loads(task.request_data) if task.request_data else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        await callback.answer("Данные исходной задачи повреждены.", show_alert=True)
        return

    user = await get_or_create_user(callback.from_user.id)
    restored = build_repeat_video_state(
        request_data,
        include_private_media=bool(task.user_id == user.id),
        task=task,
    )
    if not restored.get("user_prompt"):
        restored["user_prompt"] = str(task.prompt or "")
    restored["repeat_source_task_id"] = task_id

    model = restored["v_model"]
    billing_quote = None
    if normalize_video_model_key(model) in {"seedance_2", "seedance_2_5"}:
        quality = restored.get("seedance25_resolution", "720p") if model == "seedance_2_5" else None
        billing_quote = await quote_video_for_actor(
            callback.from_user.id, model, restored['v_duration'], quality,
            restored['v_reference_videos'],
        )
    unit_cost = billing_quote.cost if billing_quote else int(task.cost or 0)
    is_admin = billing_quote.charge_cost == 0 if billing_quote else config.is_admin(callback.from_user.id)
    if unit_cost > 0 and not is_admin:
        if not await check_can_afford(callback.from_user.id, unit_cost):
            await callback.answer("Недостаточно бананов для повтора.", show_alert=True)
            return
        if not await deduct_credits(callback.from_user.id, unit_cost):
            await callback.answer("Не удалось списать бананы.", show_alert=True)
            return

    launch_observation = {}
    try:
        await state.clear()
        await state.update_data(**restored)
        model_label = get_video_model_label(restored["v_model"])
        progress = await callback.message.answer(
            "🔁 <b>Повторяю генерацию видео</b>\n"
            f"• Модель: <code>{model_label}</code>\n"
            f"• Длительность: <code>{restored['v_duration']}с</code>\n"
            f"• Фото-референсы: <code>{len(restored['reference_images'])}</code>\n"
            f"• Видео-референсы: <code>{len(restored['v_reference_videos'])}</code>",
            parse_mode="HTML",
        )

        await progress.delete()
        await run_no_preset_video_from_callback(
            callback,
            state,
            restored["user_prompt"],
            unit_cost,
            is_admin,
            billing_quote=billing_quote,
            _launch_observation=launch_observation,
        )
    except Exception:
        logger.exception("Advanced video repeat failed for task_id=%s", task_id)
        if unit_cost > 0 and not is_admin and not launch_observation.get("accepted") and not launch_observation.get("refund_attempted"):
            launch_observation["refund_attempted"] = True
            await add_credits(callback.from_user.id, unit_cost)
        try:
            await callback.answer(
                "Не удалось подтвердить запуск повтора. Не запускайте повторно до проверки статуса.",
                show_alert=True,
            )
        except TelegramBadRequest:
            pass
