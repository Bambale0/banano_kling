"""Admin-only Seedance 2.5 preview integration.

This layer deliberately reuses the established Telegram video UX while keeping
Seedance 2.5 isolated from the stable Seedance 2.0 production adapter.
"""

from __future__ import annotations

from functools import wraps

from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.services.seedance_25_service import seedance_25_service

from . import generation as generation_module

router = Router(name="seedance_25_preview")
MODEL_KEY = "seedance_2_5"


def _is_admin(user_id: int | None) -> bool:
    return bool(user_id is not None and config.is_admin(int(user_id)))


def install_seedance_25_preview() -> None:
    """Patch narrow generation seams once for the admin preview model."""
    if getattr(generation_module, "_seedance_25_preview_installed", False):
        return

    original_show_models = generation_module._show_video_model_selection_screen
    original_apply_model = generation_module._apply_video_model_selection
    original_message_launch = generation_module.run_no_preset_video_from_message
    original_callback_launch = generation_module.run_no_preset_video_from_callback

    @wraps(original_show_models)
    async def show_models_with_admin_preview(message_or_callback, state, edit=True):
        # The keyboard builder itself performs the visibility check, but the
        # legacy screen did not pass a user id. Temporarily wrap only this call
        # by reproducing the small screen contract through the existing helper.
        data = await state.get_data()
        current_model = data.get("v_model", "v3_pro")
        user_id = getattr(getattr(message_or_callback, "from_user", None), "id", None)
        user_credits = await generation_module.get_user_credits(user_id) if user_id else 0
        text = (
            "🎬 <b>Создание видео</b>\n"
            f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
            "<b>Шаг 1. Выберите модель</b>\n"
            "Сначала выберите модель видео.\n"
            "После этого бот покажет следующий шаг именно для неё."
        )
        keyboard = generation_module.get_video_model_selection_keyboard(
            current_model,
            user_id=user_id,
        )
        try:
            if isinstance(message_or_callback, types.CallbackQuery):
                await message_or_callback.message.edit_text(
                    text, reply_markup=keyboard, parse_mode="HTML"
                )
            elif edit:
                await message_or_callback.edit_text(
                    text, reply_markup=keyboard, parse_mode="HTML"
                )
            else:
                await message_or_callback.answer(
                    text, reply_markup=keyboard, parse_mode="HTML"
                )
        except Exception:
            await message_or_callback.answer(text, reply_markup=keyboard, parse_mode="HTML")
        await state.set_state(generation_module.GenerationStates.waiting_for_input)

    @wraps(original_apply_model)
    async def apply_model_with_admin_guard(callback, state, model):
        if model == MODEL_KEY and not _is_admin(callback.from_user.id):
            await callback.answer("Модель доступна только администраторам", show_alert=True)
            return
        return await original_apply_model(callback, state, model)

    @wraps(original_message_launch)
    async def message_launch_with_seedance_25(message, state, prompt):
        data = await state.get_data()
        if data.get("v_model") != MODEL_KEY:
            return await original_message_launch(message, state, prompt)
        if not _is_admin(message.from_user.id):
            await message.answer("❌ Seedance 2.5 сейчас доступна только администраторам.")
            await state.clear()
            return
        return await _run_seedance_25_message(message, state, prompt)

    @wraps(original_callback_launch)
    async def callback_launch_with_seedance_25(callback, state, prompt, cost, is_admin):
        data = await state.get_data()
        if data.get("v_model") != MODEL_KEY:
            return await original_callback_launch(callback, state, prompt, cost, is_admin)
        if not _is_admin(callback.from_user.id):
            await callback.message.answer("❌ Seedance 2.5 сейчас доступна только администраторам.")
            await state.clear()
            return
        return await _run_seedance_25_callback(callback, state, prompt)

    generation_module._show_video_model_selection_screen = show_models_with_admin_preview
    generation_module._apply_video_model_selection = apply_model_with_admin_guard
    generation_module.run_no_preset_video_from_message = message_launch_with_seedance_25
    generation_module.run_no_preset_video_from_callback = callback_launch_with_seedance_25
    generation_module._seedance_25_preview_installed = True


async def _seedance_25_inputs(state: FSMContext) -> tuple[dict, list[str], list[str]]:
    data = await state.get_data()
    image_urls = generation_module._clean_unique_urls(
        [data.get("v_image_url"), *(data.get("reference_images") or [])]
    )[: seedance_25_service.MAX_REFERENCE_IMAGES]
    video_urls = generation_module._clean_unique_urls(
        data.get("v_reference_videos") or []
    )[: seedance_25_service.MAX_REFERENCE_VIDEOS]
    return data, image_urls, video_urls


async def _run_seedance_25_message(message: types.Message, state: FSMContext, prompt: str) -> None:
    data, image_urls, video_urls = await _seedance_25_inputs(state)
    duration = generation_module._normalize_video_duration_value(
        MODEL_KEY, int(data.get("v_duration", 5))
    )
    ratio = data.get("v_ratio", "16:9")
    processing = await message.answer(
        "🧪 <b>Seedance 2.5 — admin preview</b>\n"
        "Задача отправляется в Kie.ai…",
        parse_mode="HTML",
    )
    try:
        result = await seedance_25_service.generate_video(
            prompt=prompt,
            duration=duration,
            aspect_ratio=ratio,
            resolution="720p",
            reference_image_urls=image_urls or None,
            reference_video_urls=video_urls or None,
            generate_audio=True,
            callBackUrl=config.kie_notification_url if config.WEBHOOK_HOST else None,
        )
        await processing.delete()
        if not result or not result.get("task_id"):
            error = result.get("error") if isinstance(result, dict) else "provider response has no task_id"
            await message.answer(f"❌ Seedance 2.5 не запустилась: <code>{error}</code>", parse_mode="HTML")
            await state.clear()
            return

        user = await generation_module.get_or_create_user(message.from_user.id)
        await generation_module.add_generation_task(
            user.id,
            message.from_user.id,
            result["task_id"],
            "video",
            "no_preset_video",
            model=MODEL_KEY,
            duration=duration,
            aspect_ratio=ratio,
            prompt=prompt,
            cost=0,
            request_data={
                "source": "telegram",
                "preview": "seedance_2_5_admin",
                "v_type": data.get("v_type", "text"),
                "v_model": MODEL_KEY,
                "v_image_url": data.get("v_image_url"),
                "reference_images": image_urls,
                "v_reference_videos": video_urls,
                "resolution": "720p",
            },
        )
        await message.answer(
            "✅ <b>Seedance 2.5 запущена</b>\n"
            f"🆔 <code>{result['task_id']}</code>\n"
            f"⏱ <code>{duration}</code> сек · 📐 <code>{ratio}</code>\n"
            "🧪 Админ-тест — бананы не списываются.\n\n"
            "Результат придёт через общий Kie webhook.",
            parse_mode="HTML",
        )
    except Exception as exc:
        generation_module.logger.exception("Seedance 2.5 admin preview failed")
        try:
            await processing.delete()
        except Exception:
            pass
        await message.answer(
            f"❌ Seedance 2.5: <code>{str(exc)[:500]}</code>",
            parse_mode="HTML",
        )
    finally:
        await state.clear()


async def _run_seedance_25_callback(callback: types.CallbackQuery, state: FSMContext, prompt: str) -> None:
    # Repeat flows use the same provider task creator but answer through the
    # callback message, preserving the existing UX contract.
    await _run_seedance_25_message(callback.message, state, prompt)
    try:
        await callback.answer("Seedance 2.5 запускаю")
    except Exception:
        pass


@router.callback_query(F.data == "v_model_seedance_2_5")
async def guard_seedance_25_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Security boundary for forged callbacks before the broad legacy handler."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Модель доступна только администраторам", show_alert=True)
        return
    # Let the patched legacy selector own the normal state transition.
    raise SkipHandler
