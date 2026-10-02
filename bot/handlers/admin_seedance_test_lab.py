from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import uuid
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import aiohttp
from aiogram import F, Router, types
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.handlers.generation import (
    _persist_reusable_media_reference,
    _save_reference_image_from_message,
)
from bot.services.neironych_seedance_admin_service import (
    NeironychAPIError,
    NeironychSeedanceAdminService,
    neironych_seedance_admin_service,
)

router = Router(name="admin_seedance_test_lab")
logger = logging.getLogger(__name__)

_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()
_DELIVERED_REQUEST_IDS: set[str] = set()
_SUBMIT_LOCKS: dict[int, asyncio.Lock] = {}
_DELIVERY_LOCKS: dict[str, asyncio.Lock] = {}

_MODEL_LABELS = {
    "seedance-2.5": "Seedance 2.5",
    "seedance-2.0": "Seedance 2.0",
    "seedance-2.0-mini": "Seedance 2.0 Mini",
    "seedance-2.0-fast": "Seedance 2.0 Fast",
}
_MODE_LABELS = {
    "text": "Текст",
    "reference": "Референсы",
    "frames": "Первый/последний кадр",
    "edit": "Edit 2.5",
}
_IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png"}
_VIDEO_TYPES = {"video/mp4": "mp4", "video/quicktime": "mov"}
_AUDIO_TYPES = {"audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav"}
_IMAGE_MAX_BYTES = 20 * 1024 * 1024
_AUDIO_MAX_BYTES = 15_000_000


class SeedanceAdminTestStates(StatesGroup):
    prompt = State()
    references = State()
    frames = State()


def _is_admin(user_id: int | None) -> bool:
    return bool(user_id is not None and config.is_admin(int(user_id)))


async def _require_admin(callback: types.CallbackQuery) -> bool:
    if _is_admin(callback.from_user.id):
        return True
    await callback.answer("⛔ Нет доступа", show_alert=True)
    return False


def _defaults() -> dict[str, Any]:
    return {
        "seedance_admin_model": "seedance-2.5",
        "seedance_admin_mode": "text",
        "seedance_admin_prompt": "",
        "seedance_admin_duration": 5,
        "seedance_admin_resolution": "720p",
        "seedance_admin_ratio": "9:16",
        "seedance_admin_references": [],
        "seedance_admin_start_image": "",
        "seedance_admin_end_image": "",
        "seedance_admin_enabled_models": [],
        "seedance_admin_last_request_id": "",
        "seedance_admin_last_model": "",
        "seedance_admin_last_status": "",
        "seedance_admin_last_payload_hash": "",
        "seedance_admin_pending_key": "",
        "seedance_admin_pending_payload_hash": "",
    }


async def _data(state: FSMContext) -> dict[str, Any]:
    data = await state.get_data()
    missing = {key: value for key, value in _defaults().items() if key not in data}
    if missing:
        await state.update_data(**missing)
        data.update(missing)
    return data


def _short(value: Any, limit: int = 260) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return "не задан"
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _reference_counts(refs: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"image": 0, "video": 0, "audio": 0}
    for item in refs:
        kind = str(item.get("kind") or "")
        if kind in counts:
            counts[kind] += 1
    return counts


def _normalized_settings(data: dict[str, Any]) -> dict[str, Any]:
    model = str(data.get("seedance_admin_model") or "seedance-2.5")
    spec = NeironychSeedanceAdminService.spec(model)
    mode = str(data.get("seedance_admin_mode") or "text")
    if mode == "edit" and not spec.supports_edit:
        mode = "reference"

    duration = int(data.get("seedance_admin_duration") or spec.duration_range[0])
    duration = min(max(duration, spec.duration_range[0]), spec.duration_range[1])

    resolution = str(data.get("seedance_admin_resolution") or "")
    if resolution not in spec.resolutions:
        resolution = "720p" if "720p" in spec.resolutions else spec.resolutions[0]

    ratio = str(data.get("seedance_admin_ratio") or "9:16")
    if mode == "edit" or (mode == "frames" and model == "seedance-2.5"):
        ratio = "adaptive"
    elif ratio not in NeironychSeedanceAdminService.FIXED_RATIOS:
        ratio = "9:16"

    return {
        "seedance_admin_model": model,
        "seedance_admin_mode": mode,
        "seedance_admin_duration": duration,
        "seedance_admin_resolution": resolution,
        "seedance_admin_ratio": ratio,
    }


async def _normalize_state(state: FSMContext) -> dict[str, Any]:
    data = await _data(state)
    updates = _normalized_settings(data)
    if any(data.get(key) != value for key, value in updates.items()):
        await state.update_data(**updates)
        data.update(updates)
    return data


async def _refresh_enabled_models(state: FSMContext) -> set[str] | None:
    try:
        enabled = await neironych_seedance_admin_service.list_enabled_seedance_models()
    except Exception:
        logger.exception("Seedance admin test failed to fetch /v1/models")
        return None
    await state.update_data(seedance_admin_enabled_models=sorted(enabled))
    return enabled


def _availability_icon(model: str, enabled: set[str]) -> str:
    return "🟢" if model in enabled else "⚪"


def _dashboard_text(data: dict[str, Any]) -> str:
    model = str(data["seedance_admin_model"])
    mode = str(data["seedance_admin_mode"])
    refs = list(data.get("seedance_admin_references") or [])
    counts = _reference_counts(refs)
    enabled = set(data.get("seedance_admin_enabled_models") or [])
    key_status = "✅ настроен" if neironych_seedance_admin_service.enabled else "⚠️ не настроен"
    availability = " / ".join(
        f"{_availability_icon(model_id, enabled)} {label}"
        for model_id, label in _MODEL_LABELS.items()
    )
    duration = (
        "по исходному видео"
        if mode == "edit"
        else f"{int(data['seedance_admin_duration'])} сек"
    )
    return (
        "🎬 <b>Seedance · Нейроныч API · admin test</b>\n\n"
        f"Модель: <b>{html.escape(_MODEL_LABELS[model])}</b>\n"
        f"Режим: <b>{html.escape(_MODE_LABELS[mode])}</b>\n"
        f"Длительность: <b>{html.escape(duration)}</b>\n"
        f"Разрешение: <b>{html.escape(str(data['seedance_admin_resolution']))}</b>\n"
        f"Формат: <b>{html.escape(str(data['seedance_admin_ratio']))}</b>\n"
        f"Референсы: <b>🖼 {counts['image']} · 🎞 {counts['video']} · 🎵 {counts['audio']}</b>\n"
        f"Кадры: <b>{'✅ start' if data.get('seedance_admin_start_image') else '— start'}"
        f" / {'✅ end' if data.get('seedance_admin_end_image') else '— end'}</b>\n"
        f"API key: <b>{key_status}</b>\n\n"
        f"Промпт: <i>{html.escape(_short(data.get('seedance_admin_prompt')))}</i>\n\n"
        f"Доступность сейчас: {html.escape(availability)}\n"
        "⚪ = модель есть в документации, но сейчас отсутствует в GET /v1/models.\n\n"
        "ROX не списываются. Используется только баланс тестового API."
    )


def _dashboard_keyboard(data: dict[str, Any]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    enabled = set(data.get("seedance_admin_enabled_models") or [])
    current_model = str(data["seedance_admin_model"])
    for model, model_label in _MODEL_LABELS.items():
        label = model_label.replace("Seedance ", "")
        builder.button(
            text=(
                f"{'✅ ' if model == current_model else ''}"
                f"{_availability_icon(model, enabled)} {label}"
            ),
            callback_data=f"admin_seedance_model:{model}",
        )

    current_mode = str(data["seedance_admin_mode"])
    modes = ["text", "reference", "frames"]
    if current_model == "seedance-2.5":
        modes.append("edit")
    for mode in modes:
        builder.button(
            text=f"{'✅ ' if mode == current_mode else ''}{_MODE_LABELS[mode]}",
            callback_data=f"admin_seedance_mode:{mode}",
        )

    builder.button(text="✍️ Промпт", callback_data="admin_seedance_prompt")
    if current_mode in {"reference", "edit"}:
        refs = list(data.get("seedance_admin_references") or [])
        builder.button(
            text=f"📎 Референсы {len(refs)}",
            callback_data="admin_seedance_refs",
        )
    if current_mode == "frames":
        count = int(bool(data.get("seedance_admin_start_image"))) + int(
            bool(data.get("seedance_admin_end_image"))
        )
        builder.button(
            text=f"🎞 Кадры {count}/2",
            callback_data="admin_seedance_frames",
        )

    if current_mode != "edit":
        builder.button(
            text=f"⏱ {int(data['seedance_admin_duration'])}с",
            callback_data="admin_seedance_duration",
        )
    builder.button(
        text=f"✨ {data['seedance_admin_resolution']}",
        callback_data="admin_seedance_resolution",
    )
    builder.button(
        text=f"↔️ {data['seedance_admin_ratio']}",
        callback_data="admin_seedance_ratio",
    )
    builder.button(text="🚀 Запустить", callback_data="admin_seedance_generate")
    if data.get("seedance_admin_last_request_id"):
        builder.button(text="🔄 Проверить задачу", callback_data="admin_seedance_check")
        builder.button(text="🆕 Новый запуск", callback_data="admin_seedance_new_request")
    builder.button(text="🌐 Обновить доступность", callback_data="admin_seedance_refresh")
    builder.button(text="ℹ️ API-контракт", callback_data="admin_seedance_info")
    builder.button(text="⬅️ В тесты", callback_data="admin_test_lab")
    builder.adjust(2, 2, 2, 2, 2, 2, 1, 1, 1)
    return builder.as_markup()


async def _show_dashboard(
    message: types.Message,
    state: FSMContext,
    *,
    edit: bool,
) -> None:
    data = await _normalize_state(state)
    text = _dashboard_text(data)
    markup = _dashboard_keyboard(data)
    if edit:
        try:
            await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
            return
        except TelegramAPIError:
            pass
    await message.answer(text, reply_markup=markup, parse_mode="HTML")


def _choice_keyboard(
    values: list[str],
    current: str,
    prefix: str,
    *,
    width: int = 4,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for value in values:
        builder.button(
            text=f"{'✅ ' if value == current else ''}{value}",
            callback_data=f"{prefix}:{value}",
        )
    builder.button(text="⬅️ Назад", callback_data="admin_seedance_lab")
    builder.adjust(width)
    return builder.as_markup()


def _prompt_keyboard(has_prompt: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Готово", callback_data="admin_seedance_prompt_done")
    if has_prompt:
        builder.button(text="🗑 Очистить", callback_data="admin_seedance_prompt_clear")
    builder.button(text="⬅️ Настройки", callback_data="admin_seedance_lab")
    builder.adjust(2 if has_prompt else 1, 1)
    return builder.as_markup()


def _refs_keyboard(count: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Готово", callback_data="admin_seedance_refs_done")
    if count:
        builder.button(text="🗑 Очистить", callback_data="admin_seedance_refs_clear")
    builder.button(text="⬅️ Настройки", callback_data="admin_seedance_lab")
    builder.adjust(2 if count else 1, 1)
    return builder.as_markup()


def _frames_keyboard(count: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Готово", callback_data="admin_seedance_frames_done")
    if count:
        builder.button(text="🗑 Очистить", callback_data="admin_seedance_frames_clear")
    builder.button(text="⬅️ Настройки", callback_data="admin_seedance_lab")
    builder.adjust(2 if count else 1, 1)
    return builder.as_markup()


def _task_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Проверить", callback_data="admin_seedance_check")],
            [InlineKeyboardButton(text="🆕 Новый запуск", callback_data="admin_seedance_new_request")],
            [InlineKeyboardButton(text="⬅️ Seedance test", callback_data="admin_seedance_lab")],
        ]
    )


def _submit_lock(admin_id: int) -> asyncio.Lock:
    return _SUBMIT_LOCKS.setdefault(int(admin_id), asyncio.Lock())


def _delivery_lock(request_id: str) -> asyncio.Lock:
    return _DELIVERY_LOCKS.setdefault(str(request_id), asyncio.Lock())


def _track_background(coro: Coroutine[Any, Any, Any]) -> None:
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)

    def _done(completed: asyncio.Task[Any]) -> None:
        _BACKGROUND_TASKS.discard(completed)
        try:
            completed.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Seedance admin test background task failed")

    task.add_done_callback(_done)


def _extract_media(message: types.Message) -> tuple[str, Any, str, str] | None:
    if message.photo:
        return "image", message.photo[-1], "image/jpeg", "jpg"
    if message.video:
        mime = str(message.video.mime_type or "video/mp4")
        ext = _VIDEO_TYPES.get(mime)
        if ext:
            return "video", message.video, mime, ext
    if message.audio:
        mime = str(message.audio.mime_type or "")
        ext = _AUDIO_TYPES.get(mime)
        if ext:
            return "audio", message.audio, mime, ext
    if message.document:
        mime = str(message.document.mime_type or "")
        if mime in _IMAGE_TYPES:
            return "image", message.document, mime, _IMAGE_TYPES[mime]
        if mime in _VIDEO_TYPES:
            return "video", message.document, mime, _VIDEO_TYPES[mime]
        if mime in _AUDIO_TYPES:
            return "audio", message.document, mime, _AUDIO_TYPES[mime]
    return None


def _max_file_bytes(model: str, kind: str) -> int:
    if kind == "image":
        return _IMAGE_MAX_BYTES
    if kind == "audio":
        return _AUDIO_MAX_BYTES
    if model == "seedance-2.5":
        return 100 * 1024 * 1024
    return 50 * 1000 * 1000


async def _save_media_reference(
    message: types.Message,
    *,
    model: str,
) -> tuple[dict[str, Any] | None, str | None]:
    extracted = _extract_media(message)
    if extracted is None:
        return None, "Отправьте JPEG/PNG, MP4/MOV или WAV/MP3."
    kind, media, mime, ext = extracted
    file_size = int(getattr(media, "file_size", 0) or 0)
    max_bytes = _max_file_bytes(model, kind)
    if file_size and file_size > max_bytes:
        return None, f"Файл слишком большой для {model}: {file_size // (1024 * 1024)} МБ."

    duration = int(getattr(media, "duration", 0) or 0)
    if kind in {"video", "audio"} and duration:
        max_duration = 30 if model == "seedance-2.5" else 15
        if duration < 2 or duration > max_duration:
            return None, f"{kind}: допустимо 2–{max_duration} секунд для {model}."

    if kind == "image":
        url, error = await _save_reference_image_from_message(
            message,
            original_filename_prefix="seedance-admin-test",
        )
        if error or not url:
            return None, error or "Не удалось сохранить изображение."
    else:
        try:
            file = await message.bot.get_file(media.file_id)
            downloaded = await message.bot.download_file(file.file_path)
            payload = downloaded.read()
        except Exception:
            logger.exception("Seedance admin test failed to download %s", kind)
            return None, "❌ Не удалось скачать файл из Telegram."
        if len(payload) > max_bytes:
            return None, "❌ Файл превышает лимит Seedance."
        original_filename = getattr(media, "file_name", None) or f"seedance-admin.{ext}"
        url = await _persist_reusable_media_reference(
            message.from_user.id,
            payload,
            ext,
            kind=kind,
            original_filename=original_filename,
            content_type=mime,
        )
        if not url:
            return None, "❌ Не удалось сохранить референс."

    return {"kind": kind, "url": url, "duration": duration}, None


def _validate_reference_slot(
    *,
    model: str,
    refs: list[dict[str, Any]],
    new_kind: str,
) -> str | None:
    spec = NeironychSeedanceAdminService.spec(model)
    counts = _reference_counts(refs)
    limits = {
        "image": spec.max_images,
        "video": spec.max_videos,
        "audio": spec.max_audios,
    }
    if counts[new_kind] >= limits[new_kind]:
        return f"Лимит {new_kind}: {limits[new_kind]} для {model}."
    if len(refs) >= spec.max_references:
        return f"Общий лимит референсов: {spec.max_references} для {model}."
    return None


async def _send_result(
    bot: Any,
    chat_id: int,
    *,
    request_id: str,
    model: str,
) -> None:
    async with _delivery_lock(request_id):
        if request_id in _DELIVERED_REQUEST_IDS:
            return
        path = await neironych_seedance_admin_service.download_to_temp(request_id)
        try:
            caption = (
                "✅ <b>Seedance admin test готов</b>\n"
                f"Модель: <code>{html.escape(model)}</code>\n"
                f"Request ID: <code>{html.escape(request_id)}</code>"
            )
            try:
                await bot.send_video(
                    chat_id=chat_id,
                    video=FSInputFile(path),
                    caption=caption,
                    parse_mode="HTML",
                )
            except TelegramAPIError:
                await bot.send_document(
                    chat_id=chat_id,
                    document=FSInputFile(path),
                    caption=caption,
                    parse_mode="HTML",
                )
            _DELIVERED_REQUEST_IDS.add(request_id)
        finally:
            Path(path).unlink(missing_ok=True)

def _error_text(record: dict[str, Any]) -> str:
    error = record.get("error")
    if isinstance(error, dict):
        error = error.get("message") or error.get("type") or json.dumps(error, ensure_ascii=False)
    return _short(error or "provider error", 600)


async def _poll_and_deliver(bot: Any, chat_id: int, request_id: str, model: str) -> None:
    try:
        record = await neironych_seedance_admin_service.wait_for_result(request_id)
    except TimeoutError:
        await bot.send_message(
            chat_id,
            "⏳ Seedance всё ещё выполняется. Задача не потеряна — используйте «Проверить».\n"
            f"Request ID: <code>{html.escape(request_id)}</code>",
            parse_mode="HTML",
        )
        return
    status = str(record.get("status") or "").lower()
    if status == "done":
        await _send_result(bot, chat_id, request_id=request_id, model=model)
        return
    await bot.send_message(
        chat_id,
        "❌ <b>Seedance admin test завершился ошибкой</b>\n"
        f"Статус: <code>{html.escape(status)}</code>\n"
        f"Request ID: <code>{html.escape(request_id)}</code>\n"
        f"{html.escape(_error_text(record))}",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_seedance_lab")
async def open_seedance_lab(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.set_state(None)
    await _refresh_enabled_models(state)
    if callback.message is not None:
        await _show_dashboard(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(F.data == "admin_seedance_refresh")
async def refresh_seedance_models(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    enabled = await _refresh_enabled_models(state)
    if callback.message is not None:
        await _show_dashboard(callback.message, state, edit=True)
    await callback.answer(
        "Доступность обновлена" if enabled is not None else "Не удалось получить /v1/models",
        show_alert=enabled is None,
    )


@router.callback_query(F.data.startswith("admin_seedance_model:"))
async def choose_model(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    model = (callback.data or "").split(":", 1)[1]
    if model not in NeironychSeedanceAdminService.MODEL_SPECS:
        await callback.answer("Неизвестная модель", show_alert=True)
        return
    await state.update_data(seedance_admin_model=model)
    await _normalize_state(state)
    if callback.message is not None:
        await _show_dashboard(callback.message, state, edit=True)
    await callback.answer(_MODEL_LABELS[model])


@router.callback_query(F.data.startswith("admin_seedance_mode:"))
async def choose_mode(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    mode = (callback.data or "").split(":", 1)[1]
    data = await _data(state)
    model = str(data["seedance_admin_model"])
    if mode not in {"text", "reference", "frames", "edit"}:
        await callback.answer("Неизвестный режим", show_alert=True)
        return
    if mode == "edit" and model != "seedance-2.5":
        await callback.answer("Edit есть только у Seedance 2.5", show_alert=True)
        return
    await state.update_data(seedance_admin_mode=mode)
    await _normalize_state(state)
    if callback.message is not None:
        await _show_dashboard(callback.message, state, edit=True)
    await callback.answer(_MODE_LABELS[mode])


@router.callback_query(F.data == "admin_seedance_prompt")
async def start_prompt(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    data = await _data(state)
    prompt = str(data.get("seedance_admin_prompt") or "")
    await state.set_state(SeedanceAdminTestStates.prompt)
    if callback.message is not None:
        await callback.message.edit_text(
            "✍️ <b>Seedance · промпт</b>\n\n"
            "Отправьте текст промпта. Для multimodal можно использовать "
            "@Image 1, @Video 1, @Audio 1.",
            reply_markup=_prompt_keyboard(bool(prompt)),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(SeedanceAdminTestStates.prompt)
async def receive_prompt(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        await state.clear()
        return
    prompt = str(message.text or message.caption or "").strip()
    if not prompt:
        await message.answer("Нужен текстовый промпт.")
        return
    await state.update_data(seedance_admin_prompt=prompt)
    await message.answer(
        f"✅ Промпт сохранён: <b>{len(prompt)}</b> символов.",
        reply_markup=_prompt_keyboard(True),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_seedance_prompt_done")
async def finish_prompt(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.set_state(None)
    if callback.message is not None:
        await _show_dashboard(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(F.data == "admin_seedance_prompt_clear")
async def clear_prompt(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.update_data(seedance_admin_prompt="")
    await state.set_state(SeedanceAdminTestStates.prompt)
    if callback.message is not None:
        await callback.message.edit_text(
            "✍️ <b>Seedance · промпт</b>\n\nПромпт очищен.",
            reply_markup=_prompt_keyboard(False),
            parse_mode="HTML",
        )
    await callback.answer("Очищено")


@router.callback_query(F.data == "admin_seedance_refs")
async def start_refs(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    data = await _normalize_state(state)
    mode = str(data["seedance_admin_mode"])
    if mode not in {"reference", "edit"}:
        await callback.answer("Сначала выберите режим «Референсы» или Edit", show_alert=True)
        return
    refs = list(data.get("seedance_admin_references") or [])
    await state.set_state(SeedanceAdminTestStates.references)
    model = str(data["seedance_admin_model"])
    spec = NeironychSeedanceAdminService.spec(model)
    text = (
        f"📎 <b>{html.escape(_MODEL_LABELS[model])} · референсы</b>\n\n"
        + (
            "Edit: первый MP4/MOV — редактируемый; можно добавить "
            "поддерживающие фото/видео/аудио референсы.\n"
            if mode == "edit"
            else "Отправляйте JPEG/PNG, MP4/MOV или WAV/MP3.\n"
        )
        + (
            f"Лимиты: фото {spec.max_images}, видео {spec.max_videos}, "
            f"аудио {spec.max_audios}, всего {spec.max_references}.\n"
        )
        + f"Сейчас: <b>{len(refs)}</b>."
    )
    if callback.message is not None:
        await callback.message.edit_text(
            text,
            reply_markup=_refs_keyboard(len(refs)),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(SeedanceAdminTestStates.references)
async def receive_reference(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        await state.clear()
        return
    data = await _normalize_state(state)
    model = str(data["seedance_admin_model"])
    mode = str(data["seedance_admin_mode"])
    refs = list(data.get("seedance_admin_references") or [])
    extracted = _extract_media(message)
    if extracted is None:
        await message.answer(
            "Отправьте JPEG/PNG, MP4/MOV или WAV/MP3.",
            reply_markup=_refs_keyboard(len(refs)),
        )
        return
    kind = extracted[0]
    has_edit_source = any(item.get("kind") == "video" for item in refs)
    if mode == "edit" and not has_edit_source and kind != "video":
        await message.answer(
            "Сначала отправьте исходный MP4/MOV — он будет @Video 1 и edit-source.",
            reply_markup=_refs_keyboard(len(refs)),
        )
        return

    slot_error = _validate_reference_slot(model=model, refs=refs, new_kind=kind)
    if slot_error:
        await message.answer(slot_error, reply_markup=_refs_keyboard(len(refs)))
        return

    item, error = await _save_media_reference(
        message,
        model=model,
    )
    if error or item is None:
        await message.answer(
            error or "Не удалось сохранить референс.",
            reply_markup=_refs_keyboard(len(refs)),
        )
        return
    if not any(str(existing.get("url")) == item["url"] for existing in refs):
        refs.append(item)
    await state.update_data(seedance_admin_references=refs)
    counts = _reference_counts(refs)
    await message.answer(
        (
            f"✅ Добавлено. Всего <b>{len(refs)}</b>: "
            f"🖼 {counts['image']} · 🎞 {counts['video']} · 🎵 {counts['audio']}"
        ),
        reply_markup=_refs_keyboard(len(refs)),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_seedance_refs_done")
async def finish_refs(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.set_state(None)
    if callback.message is not None:
        await _show_dashboard(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(F.data == "admin_seedance_refs_clear")
async def clear_refs(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.update_data(seedance_admin_references=[])
    await state.set_state(SeedanceAdminTestStates.references)
    if callback.message is not None:
        await callback.message.edit_text(
            "📎 <b>Seedance · референсы</b>\n\nОчищено.",
            reply_markup=_refs_keyboard(0),
            parse_mode="HTML",
        )
    await callback.answer("Очищено")


@router.callback_query(F.data == "admin_seedance_frames")
async def start_frames(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    data = await _normalize_state(state)
    if data["seedance_admin_mode"] != "frames":
        await callback.answer("Сначала выберите режим кадров", show_alert=True)
        return
    count = int(bool(data.get("seedance_admin_start_image"))) + int(
        bool(data.get("seedance_admin_end_image"))
    )
    await state.set_state(SeedanceAdminTestStates.frames)
    if callback.message is not None:
        await callback.message.edit_text(
            "🎞 <b>Seedance · первый/последний кадр</b>\n\n"
            "Отправьте первое JPEG/PNG — это start_image. Второе — end_image. "
            "Последний кадр необязателен.",
            reply_markup=_frames_keyboard(count),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(SeedanceAdminTestStates.frames)
async def receive_frame(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        await state.clear()
        return
    data = await _normalize_state(state)
    count = int(bool(data.get("seedance_admin_start_image"))) + int(
        bool(data.get("seedance_admin_end_image"))
    )
    extracted = _extract_media(message)
    if extracted is None or extracted[0] != "image":
        await message.answer("Нужен JPEG/PNG.", reply_markup=_frames_keyboard(count))
        return
    media = extracted[1]
    if int(getattr(media, "file_size", 0) or 0) > _IMAGE_MAX_BYTES:
        await message.answer("Изображение больше 20 MiB.", reply_markup=_frames_keyboard(count))
        return
    if count >= 2:
        await message.answer(
            "Уже заданы start и end. Сначала очистите кадры.",
            reply_markup=_frames_keyboard(count),
        )
        return
    url, error = await _save_reference_image_from_message(
        message,
        original_filename_prefix="seedance-admin-frame",
    )
    if error or not url:
        await message.answer(
            error or "Не удалось сохранить кадр.",
            reply_markup=_frames_keyboard(count),
        )
        return
    if not data.get("seedance_admin_start_image"):
        await state.update_data(seedance_admin_start_image=url)
        label = "start_image"
    else:
        await state.update_data(seedance_admin_end_image=url)
        label = "end_image"
    count += 1
    await message.answer(
        f"✅ {label} сохранён. Кадров: {count}/2.",
        reply_markup=_frames_keyboard(count),
    )


@router.callback_query(F.data == "admin_seedance_frames_done")
async def finish_frames(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.set_state(None)
    if callback.message is not None:
        await _show_dashboard(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(F.data == "admin_seedance_frames_clear")
async def clear_frames(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.update_data(
        seedance_admin_start_image="",
        seedance_admin_end_image="",
    )
    await state.set_state(SeedanceAdminTestStates.frames)
    if callback.message is not None:
        await callback.message.edit_text(
            "🎞 <b>Seedance · кадры</b>\n\nОчищено. Отправьте start_image.",
            reply_markup=_frames_keyboard(0),
            parse_mode="HTML",
        )
    await callback.answer("Очищено")


@router.callback_query(F.data == "admin_seedance_duration")
async def choose_duration(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    data = await _normalize_state(state)
    if data["seedance_admin_mode"] == "edit":
        await callback.answer("В edit длительность берётся из исходного видео", show_alert=True)
        return
    spec = NeironychSeedanceAdminService.spec(str(data["seedance_admin_model"]))
    values = [str(value) for value in range(spec.duration_range[0], spec.duration_range[1] + 1)]
    if callback.message is not None:
        await callback.message.edit_text(
            "⏱ <b>Seedance · длительность</b>",
            reply_markup=_choice_keyboard(
                values,
                str(data["seedance_admin_duration"]),
                "admin_seedance_duration_set",
                width=5,
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_seedance_duration_set:"))
async def set_duration(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    value = int((callback.data or "").split(":", 1)[1])
    data = await _normalize_state(state)
    spec = NeironychSeedanceAdminService.spec(str(data["seedance_admin_model"]))
    if not spec.duration_range[0] <= value <= spec.duration_range[1]:
        await callback.answer("Недопустимая длительность", show_alert=True)
        return
    await state.update_data(seedance_admin_duration=value)
    if callback.message is not None:
        await _show_dashboard(callback.message, state, edit=True)
    await callback.answer(f"{value} сек")


@router.callback_query(F.data == "admin_seedance_resolution")
async def choose_resolution(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    data = await _normalize_state(state)
    spec = NeironychSeedanceAdminService.spec(str(data["seedance_admin_model"]))
    if callback.message is not None:
        await callback.message.edit_text(
            "✨ <b>Seedance · resolution</b>",
            reply_markup=_choice_keyboard(
                list(spec.resolutions),
                str(data["seedance_admin_resolution"]),
                "admin_seedance_resolution_set",
                width=4,
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_seedance_resolution_set:"))
async def set_resolution(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    value = (callback.data or "").split(":", 1)[1]
    data = await _normalize_state(state)
    spec = NeironychSeedanceAdminService.spec(str(data["seedance_admin_model"]))
    if value not in spec.resolutions:
        await callback.answer("Недоступное разрешение", show_alert=True)
        return
    await state.update_data(seedance_admin_resolution=value)
    if callback.message is not None:
        await _show_dashboard(callback.message, state, edit=True)
    await callback.answer(value)


@router.callback_query(F.data == "admin_seedance_ratio")
async def choose_ratio(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    data = await _normalize_state(state)
    model = str(data["seedance_admin_model"])
    mode = str(data["seedance_admin_mode"])
    if mode == "edit" or (mode == "frames" and model == "seedance-2.5"):
        await callback.answer("В этом режиме используется adaptive", show_alert=True)
        return
    values = list(NeironychSeedanceAdminService.FIXED_RATIOS)
    if callback.message is not None:
        await callback.message.edit_text(
            "↔️ <b>Seedance · aspect_ratio</b>",
            reply_markup=_choice_keyboard(
                values,
                str(data["seedance_admin_ratio"]),
                "admin_seedance_ratio_set",
                width=3,
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_seedance_ratio_set:"))
async def set_ratio(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    value = (callback.data or "").split(":", 1)[1]
    if value not in NeironychSeedanceAdminService.FIXED_RATIOS:
        await callback.answer("Недопустимый формат", show_alert=True)
        return
    await state.update_data(seedance_admin_ratio=value)
    if callback.message is not None:
        await _show_dashboard(callback.message, state, edit=True)
    await callback.answer(value)


def _payload_from_state(data: dict[str, Any]) -> dict[str, Any]:
    model = str(data["seedance_admin_model"])
    mode = str(data["seedance_admin_mode"])
    refs = list(data.get("seedance_admin_references") or [])
    images = [str(item["url"]) for item in refs if item.get("kind") == "image"]
    videos = [str(item["url"]) for item in refs if item.get("kind") == "video"]
    audios = [str(item["url"]) for item in refs if item.get("kind") == "audio"]
    return NeironychSeedanceAdminService.build_payload(
        model=model,
        mode=mode,
        prompt=str(data.get("seedance_admin_prompt") or ""),
        duration=int(data["seedance_admin_duration"]),
        resolution=str(data["seedance_admin_resolution"]),
        aspect_ratio=str(data["seedance_admin_ratio"]),
        reference_images=images if mode in {"reference", "edit"} else None,
        reference_videos=videos if mode in {"reference", "edit"} else None,
        reference_audios=audios if mode in {"reference", "edit"} else None,
        start_image=str(data.get("seedance_admin_start_image") or "") if mode == "frames" else "",
        end_image=str(data.get("seedance_admin_end_image") or "") if mode == "frames" else "",
    )


@router.callback_query(F.data == "admin_seedance_generate")
async def generate_seedance(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    if callback.message is None:
        return
    async with _submit_lock(callback.from_user.id):
        data = await _normalize_state(state)
        if not neironych_seedance_admin_service.enabled:
            await callback.answer("NEIRONYCH_API_KEY не настроен на сервере", show_alert=True)
            return

        enabled = await _refresh_enabled_models(state)
        data = await _normalize_state(state)
        model = str(data["seedance_admin_model"])
        if enabled is not None and model not in enabled:
            await callback.answer(
                f"{model} сейчас отсутствует в GET /v1/models",
                show_alert=True,
            )
            return

        try:
            payload = _payload_from_state(data)
        except (ValueError, TypeError) as exc:
            await callback.answer(str(exc)[:180], show_alert=True)
            return

        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        if (
            data.get("seedance_admin_last_request_id")
            and str(data.get("seedance_admin_last_payload_hash") or "") == payload_hash
        ):
            await callback.answer(
                "Эта конфигурация уже запущена. Нажмите «Новый запуск» для повторной платной задачи.",
                show_alert=True,
            )
            return

        pending_key = str(data.get("seedance_admin_pending_key") or "")
        if (
            not pending_key
            or str(data.get("seedance_admin_pending_payload_hash") or "") != payload_hash
        ):
            pending_key = str(uuid.uuid4())
            await state.update_data(
                seedance_admin_pending_key=pending_key,
                seedance_admin_pending_payload_hash=payload_hash,
            )

        await callback.answer("Отправляю в Нейроныч API…")
        try:
            result = await neironych_seedance_admin_service.submit(
                payload,
                idempotency_key=pending_key,
            )
        except (
            NeironychAPIError,
            RuntimeError,
            ValueError,
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ) as exc:
            logger.exception("Seedance admin test submit failed")
            await callback.message.edit_text(
                "❌ <b>Не удалось создать Seedance-задачу.</b>\n\n"
                f"{html.escape(str(exc)[:800])}\n\n"
                "Idempotency-Key сохранён: повтор этой же конфигурации "
                "не создаст новую платную операцию.",
                reply_markup=_dashboard_keyboard(data),
                parse_mode="HTML",
            )
            return
        except Exception:
            logger.exception("Unexpected Seedance admin test submit failure")
            await callback.message.edit_text(
                "❌ Не удалось отправить задачу в Нейроныч API.",
                reply_markup=_dashboard_keyboard(data),
            )
            return

        request_id = str(result["request_id"])
        await state.update_data(
            seedance_admin_last_request_id=request_id,
            seedance_admin_last_model=model,
            seedance_admin_last_status="pending",
            seedance_admin_last_payload_hash=payload_hash,
            seedance_admin_pending_key="",
            seedance_admin_pending_payload_hash="",
        )
        await callback.message.edit_text(
            "⏳ <b>Seedance admin test запущен</b>\n\n"
            f"Модель: <code>{html.escape(model)}</code>\n"
            f"Request ID: <code>{html.escape(request_id)}</code>\n\n"
            "Результат придёт сюда автоматически. Статус можно проверить вручную.",
            reply_markup=_task_keyboard(),
            parse_mode="HTML",
        )
        _track_background(
            _poll_and_deliver(
                callback.bot,
                callback.from_user.id,
                request_id,
                model,
            )
        )


@router.callback_query(F.data == "admin_seedance_new_request")
async def new_seedance_request(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.update_data(
        seedance_admin_last_request_id="",
        seedance_admin_last_model="",
        seedance_admin_last_status="",
        seedance_admin_last_payload_hash="",
        seedance_admin_pending_key="",
        seedance_admin_pending_payload_hash="",
    )
    if callback.message is not None:
        data = await _normalize_state(state)
        await callback.message.edit_text(
            _dashboard_text(data),
            reply_markup=_dashboard_keyboard(data),
            parse_mode="HTML",
        )
    await callback.answer("Готово к новому запуску")


@router.callback_query(F.data == "admin_seedance_check")
async def check_seedance(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    data = await _data(state)
    request_id = str(data.get("seedance_admin_last_request_id") or "").strip()
    if not request_id:
        await callback.answer("Нет последней задачи", show_alert=True)
        return
    await callback.answer("Проверяю…")
    try:
        record = await neironych_seedance_admin_service.get_status(request_id)
    except Exception as exc:
        logger.exception("Seedance admin test status lookup failed")
        await callback.answer(str(exc)[:180] or "Не удалось получить статус", show_alert=True)
        return

    status = str(record.get("status") or "unknown").lower()
    await state.update_data(seedance_admin_last_status=status)
    model = str(data.get("seedance_admin_last_model") or data.get("seedance_admin_model") or "")
    if status == "done":
        if callback.message is not None:
            await callback.message.edit_text(
                "✅ <b>Seedance готов</b>\n"
                f"Request ID: <code>{html.escape(request_id)}</code>",
                reply_markup=_task_keyboard(),
                parse_mode="HTML",
            )
        await _send_result(callback.bot, callback.from_user.id, request_id=request_id, model=model)
        return

    if status in {"failed", "expired"}:
        if callback.message is not None:
            await callback.message.edit_text(
                "❌ <b>Seedance завершился ошибкой</b>\n"
                f"Статус: <code>{html.escape(status)}</code>\n"
                f"Request ID: <code>{html.escape(request_id)}</code>\n"
                f"{html.escape(_error_text(record))}",
                reply_markup=_task_keyboard(),
                parse_mode="HTML",
            )
        return

    if callback.message is not None:
        await callback.message.edit_text(
            "⏳ <b>Seedance ещё выполняется</b>\n"
            f"Статус: <code>{html.escape(status)}</code>\n"
            f"Request ID: <code>{html.escape(request_id)}</code>",
            reply_markup=_task_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "admin_seedance_info")
async def seedance_info(callback: types.CallbackQuery) -> None:
    if not await _require_admin(callback):
        return
    if callback.message is not None:
        await callback.message.edit_text(
            "ℹ️ <b>Seedance · Нейроныч API</b>\n\n"
            "Документированные модели:\n"
            "• seedance-2.5 — 4–30с, 480p/720p/1080p, refs 30/10/10/50, reference + edit.\n"
            "• seedance-2.0 — 4–15с, 480p/720p/1080p/4k, refs 9/3/3/12.\n"
            "• seedance-2.0-mini — 4–15с, 480p/720p, refs 9/3/3/12.\n"
            "• seedance-2.0-fast — 4–15с, 480p/720p, refs 9/3/3/12.\n\n"
            "Форматы: 1:1, 16:9, 9:16, 4:3, 3:4, 21:9. "
            "У 2.5 для first/last frame и edit используется adaptive.\n"
            "Seedance 2.5 edit: первый reference_video — редактируемый, duration=-1.\n"
            "Seedance 2.0/Mini/Fast не принимают audio-only: нужен image/video вместе с аудио.\n\n"
            "POST генерации не ретраится автоматически. Один Idempotency-Key сохраняется "
            "для одной конфигурации до получения request_id. Статус опрашивается через "
            "GET /v1/videos/{request_id}; готовый MP4 скачивается "
            "с авторизацией и отправляется админу.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_seedance_lab")]
                ]
            ),
            parse_mode="HTML",
        )
    await callback.answer()
