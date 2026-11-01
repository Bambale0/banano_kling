"""Closed WAN 3.0 via Neironych Telegram lab; never used by public WAN routing."""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import uuid
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
from bot.handlers.admin_seedance_test_lab import _extract_media, _save_media_reference
from bot.services.neironych_wan3_admin_service import (
    NeironychWan3AdminService,
    neironych_wan3_admin_service,
)

router = Router(name="admin_wan3_neironych_lab")
logger = logging.getLogger(__name__)
_bg_tasks: set[asyncio.Task[Any]] = set()
_submit_locks: dict[int, asyncio.Lock] = {}
_delivery_locks: dict[str, asyncio.Lock] = {}
_delivered: set[str] = set()
MODES = {"text": "Текст", "reference": "Референсы", "frames": "Кадры", "edit": "Редактирование"}

class Wan3LabStates(StatesGroup):
    dashboard = State()
    prompt = State()
    references = State()
    frames = State()
    seed = State()


def _is_admin(user_id: int | None) -> bool:
    return bool(user_id is not None and config.is_admin(int(user_id)))


async def _require_admin(callback: types.CallbackQuery) -> bool:
    if _is_admin(callback.from_user.id):
        return True
    await callback.answer("⛔ Нет доступа", show_alert=True)
    return False


def _lock(user_id: int) -> asyncio.Lock:
    return _submit_locks.setdefault(user_id, asyncio.Lock())


def _defaults() -> dict[str, Any]:
    return {
        "wan_lab_mode": "text", "wan_lab_prompt": "", "wan_lab_duration": 5,
        "wan_lab_resolution": "720p", "wan_lab_ratio": "16:9",
        "wan_lab_audio": True, "wan_lab_seed": None,
        "wan_lab_references": [], "wan_lab_start": "", "wan_lab_end": "",
        "wan_lab_last_id": "", "wan_lab_last_hash": "",
        "wan_lab_last_status": "", "wan_lab_pending_key": "",
        "wan_lab_pending_hash": "",
    }


async def _data(state: FSMContext) -> dict[str, Any]:
    data = await state.get_data()
    missing = {k: v for k, v in _defaults().items() if k not in data}
    if missing:
        await state.update_data(**missing)
        data.update(missing)
    return data


def _counts(refs: list[dict[str, Any]]) -> dict[str, int]:
    return {kind: sum(x.get("kind") == kind for x in refs) for kind in ("image", "video", "audio")}


def _payload(data: dict[str, Any]) -> dict[str, Any]:
    mode = data["wan_lab_mode"]
    refs = data.get("wan_lab_references") or []
    return NeironychWan3AdminService.build_payload(
        mode=mode, prompt=str(data.get("wan_lab_prompt") or ""),
        duration=int(data["wan_lab_duration"]),
        resolution=str(data["wan_lab_resolution"]),
        aspect_ratio=str(data["wan_lab_ratio"]),
        generate_audio=data["wan_lab_audio"], seed=data.get("wan_lab_seed"),
        reference_images=[x["url"] for x in refs if x.get("kind") == "image"] if mode in {"reference", "edit"} else None,
        reference_videos=[x["url"] for x in refs if x.get("kind") == "video"] if mode in {"reference", "edit"} else None,
        reference_audios=[x["url"] for x in refs if x.get("kind") == "audio"] if mode in {"reference", "edit"} else None,
        start_image=data.get("wan_lab_start", "") if mode == "frames" else "",
        end_image=data.get("wan_lab_end", "") if mode == "frames" else "",
    )


def _keyboard(data: dict[str, Any]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for mode, label in MODES.items():
        b.button(text=("✅ " if data["wan_lab_mode"] == mode else "") + label,
                 callback_data=f"admin_wan3:mode:{mode}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text="✍️ Промпт", callback_data="admin_wan3:prompt"))
    mode = data["wan_lab_mode"]
    if mode in {"reference", "edit"}:
        b.row(InlineKeyboardButton(text="📎 Референсы", callback_data="admin_wan3:refs"))
    elif mode == "frames":
        b.row(InlineKeyboardButton(text="🖼 Первый / последний кадр", callback_data="admin_wan3:frames"))
    if mode != "edit":
        b.row(InlineKeyboardButton(text=f"⏱ {data['wan_lab_duration']}с", callback_data="admin_wan3:duration"),
              InlineKeyboardButton(text=str(data["wan_lab_ratio"]), callback_data="admin_wan3:ratio"))
    b.row(InlineKeyboardButton(text=str(data["wan_lab_resolution"]), callback_data="admin_wan3:resolution"),
          InlineKeyboardButton(text="🔊 Звук" if data["wan_lab_audio"] else "🔇 Без звука", callback_data="admin_wan3:audio"))
    b.row(InlineKeyboardButton(text=f"🎲 Seed: {data['wan_lab_seed'] if data['wan_lab_seed'] is not None else 'Auto'}",
                               callback_data="admin_wan3:seed"))
    b.row(InlineKeyboardButton(text="🚀 Запустить через Нейроныча", callback_data="admin_wan3:generate"))
    if data["wan_lab_last_id"]:
        b.row(InlineKeyboardButton(text="🔄 Проверить задачу", callback_data="admin_wan3:check"),
              InlineKeyboardButton(text="🆕 Новый запуск", callback_data="admin_wan3:new"))
    b.row(InlineKeyboardButton(text="🌐 Проверить модель", callback_data="admin_wan3:refresh"),
          InlineKeyboardButton(text="⬅️ В тесты", callback_data="admin_test_lab"))
    return b.as_markup()


def _dashboard_text(data: dict[str, Any]) -> str:
    refs = _counts(data["wan_lab_references"])
    prompt = str(data["wan_lab_prompt"] or "").strip()
    excerpt = " ".join(prompt.split())[:180] if prompt else "не задан"
    return (
        "🧪 <b>WAN 3.0 · Нейроныч</b>\n"
        "Закрытая проверка, только админы. Бананы не списываются; "
        "запуск оплачивается балансом API.\n\n"
        f"Режим: <b>{MODES[data['wan_lab_mode']]}</b>\n"
        f"Длительность: <b>{'автоматически' if data['wan_lab_mode'] == 'edit' else str(data['wan_lab_duration']) + 'с'}</b>\n"
        f"Разрешение: <b>{data['wan_lab_resolution']}</b> · Формат: <b>{'auto' if data['wan_lab_mode'] == 'edit' else data['wan_lab_ratio']}</b>\n"
        f"Фото/видео/аудио: <b>{refs['image']}/{refs['video']}/{refs['audio']}</b>\n"
        f"Кадры: <b>{int(bool(data['wan_lab_start'])) + int(bool(data['wan_lab_end']))}/2</b>\n"
        f"Промпт: <i>{html.escape(excerpt)}</i>\n"
        f"Последний Request ID: <code>{html.escape(data['wan_lab_last_id'] or 'нет')}</code>\n\n"
        "В Edit первое видео — Video1. Для него API не принимает duration/aspect_ratio. "
        "При неизвестном результате POST повторяем с тем же ключом."
    )


async def _show(message: types.Message, state: FSMContext) -> None:
    data = await _data(state)
    try:
        await message.edit_text(_dashboard_text(data), reply_markup=_keyboard(data), parse_mode="HTML")
    except TelegramAPIError:
        await message.answer(_dashboard_text(data), reply_markup=_keyboard(data), parse_mode="HTML")


def _back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Настройки WAN", callback_data="admin_wan3:back")]
    ])


def _select_keyboard(kind: str, values: list[str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for value in values:
        b.button(text=value, callback_data=f"admin_wan3:set_{kind}:{value}")
    b.adjust(4)
    b.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_wan3:back"))
    return b.as_markup()


def _track(coro: Any) -> None:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    def done(completed: asyncio.Task[Any]) -> None:
        _bg_tasks.discard(completed)
        try:
            completed.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("WAN3 admin background check failed")
    task.add_done_callback(done)


async def _deliver(bot: Any, chat_id: int, request_id: str) -> None:
    async with _delivery_locks.setdefault(request_id, asyncio.Lock()):
        if request_id in _delivered:
            return
        path = await neironych_wan3_admin_service.download_to_temp(request_id)
        try:
            caption = f"✅ WAN 3.0 · Нейроныч\nRequest ID: <code>{html.escape(request_id)}</code>"
            try:
                await bot.send_video(chat_id, FSInputFile(path), caption=caption, parse_mode="HTML")
            except TelegramAPIError:
                await bot.send_document(chat_id, FSInputFile(path), caption=caption, parse_mode="HTML")
            _delivered.add(request_id)
            logger.info("WAN3 admin result delivered admin_id=%s request_id=%s", chat_id, request_id)
        finally:
            Path(path).unlink(missing_ok=True)


async def _poll(bot: Any, chat_id: int, request_id: str) -> None:
    try:
        record = await neironych_wan3_admin_service.wait_for_result(request_id)
        status = str(record.get("status") or "").lower()
        if status == "done":
            await _deliver(bot, chat_id, request_id)
            return
        await bot.send_message(chat_id, "❌ WAN 3.0 завершился: "
                               + html.escape(status) + "\nRequest ID: <code>"
                               + html.escape(request_id) + "</code>", parse_mode="HTML")
    except Exception as exc:
        logger.warning("WAN3 admin task needs manual recovery request_id=%s error_type=%s",
                       request_id, type(exc).__name__)
        await bot.send_message(chat_id, "⚠️ Автопроверка WAN 3.0 прервалась. "
                               "Не запускайте заново: нажмите «Проверить задачу».\n"
                               f"Request ID: <code>{html.escape(request_id)}</code>", parse_mode="HTML")


@router.callback_query(F.data == "admin_wan3:open")
async def open_lab(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.set_state(Wan3LabStates.dashboard)
    if callback.message:
        await _show(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "admin_wan3:back")
async def back(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.set_state(Wan3LabStates.dashboard)
    if callback.message:
        await _show(callback.message, state)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_wan3:mode:"))
async def set_mode(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    mode = (callback.data or "").rsplit(":", 1)[-1]
    if mode not in MODES:
        await callback.answer("Недопустимый режим", show_alert=True)
        return
    await state.update_data(wan_lab_mode=mode)
    await state.set_state(Wan3LabStates.dashboard)
    if callback.message:
        await _show(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "admin_wan3:prompt")
async def edit_prompt(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.set_state(Wan3LabStates.prompt)
    if callback.message:
        await callback.message.edit_text("✍️ Отправьте промпт. Следующие сообщения добавляются с новой строки. "
                                         "Для @Image 1/@Video 1/@Audio 1 сначала загрузите референсы.",
                                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                             [InlineKeyboardButton(text="🗑 Очистить", callback_data="admin_wan3:clear_prompt")],
                                             [InlineKeyboardButton(text="⬅️ Готово", callback_data="admin_wan3:back")],
                                         ]))
    await callback.answer()


@router.message(Wan3LabStates.prompt)
async def receive_prompt(message: types.Message, state: FSMContext) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        await state.clear()
        return
    async with _lock(message.from_user.id):
        part = str(message.text or message.caption or "").strip()
        if not part:
            await message.answer("Нужен текстовый промпт.")
            return
        data = await _data(state)
        combined = (str(data["wan_lab_prompt"]).rstrip() + "\n" + part).strip()
        if len(combined) > NeironychWan3AdminService.MAX_PROMPT_CHARS:
            await message.answer("Промпт превышает 20 000 символов.")
            return
        await state.update_data(wan_lab_prompt=combined)
        await message.answer("✅ Промпт обновлён.", reply_markup=_back())


@router.callback_query(F.data == "admin_wan3:clear_prompt")
async def clear_prompt(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.update_data(wan_lab_prompt="")
    await state.set_state(Wan3LabStates.prompt)
    if callback.message:
        await callback.message.edit_text("Промпт очищен. Отправьте новый текст.", reply_markup=_back())
    await callback.answer()


@router.callback_query(F.data.in_({"admin_wan3:refs", "admin_wan3:frames"}))
async def start_upload(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    frames = callback.data == "admin_wan3:frames"
    data = await _data(state)
    if (frames and data["wan_lab_mode"] != "frames") or (not frames and data["wan_lab_mode"] not in {"reference", "edit"}):
        await callback.answer("Сначала выберите совместимый режим.", show_alert=True)
        return
    await state.set_state(Wan3LabStates.frames if frames else Wan3LabStates.references)
    if callback.message:
        await callback.message.edit_text(
            ("🖼 Отправьте первое и при необходимости последнее фото JPEG/PNG." if frames else
             "📎 Отправьте фото, MP4/MOV или WAV/MP3. До 10 фото, 5 видео, 5 аудио, 20 всего. "
             "Видео/аудио по 2–15 секунд. В Edit первое видео — исходник."),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🗑 Очистить", callback_data="admin_wan3:clear_media")],
                [InlineKeyboardButton(text="⬅️ Готово", callback_data="admin_wan3:back")],
            ]),
        )
    await callback.answer()


@router.message(Wan3LabStates.references)
@router.message(Wan3LabStates.frames)
@router.message(Wan3LabStates.dashboard, ~F.text.startswith("/"))
async def receive_media(message: types.Message, state: FSMContext) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        await state.clear()
        return
    async with _lock(message.from_user.id):
        data = await _data(state)
        mode = data["wan_lab_mode"]
        if mode not in {"reference", "edit", "frames"}:
            await message.answer("Выберите режим референсов, кадров или редактирования.")
            return
        extracted = _extract_media(message)
        if not extracted or (mode == "frames" and extracted[0] != "image"):
            await message.answer("Отправьте JPEG/PNG, MP4/MOV или WAV/MP3 (для кадров только фото).")
            return
        kind = extracted[0]
        refs = list(data.get("wan_lab_references") or [])
        counts = _counts(refs)
        if mode == "frames":
            if data["wan_lab_start"] and data["wan_lab_end"]:
                await message.answer("Кадры уже заполнены. Нажмите «Очистить».")
                return
        elif counts[kind] >= NeironychWan3AdminService.MAX_REFERENCE_COUNTS[kind] or len(refs) >= NeironychWan3AdminService.MAX_REFERENCES:
            await message.answer("Лимит референсов для WAN 3.0 достигнут.")
            return
        # Shared Telegram media saver enforces the WAN 15s reference duration.
        saved, error = await _save_media_reference(message, model="wan-3")
        if error or not saved:
            await message.answer(error or "Не удалось сохранить медиа.")
            return
        if mode == "frames":
            key = "wan_lab_start" if not data["wan_lab_start"] else "wan_lab_end"
            await state.update_data(**{key: saved["url"]})
        else:
            refs.append(saved)
            await state.update_data(wan_lab_references=refs)
        await message.answer("✅ Материал сохранён.", reply_markup=_back())


@router.callback_query(F.data == "admin_wan3:clear_media")
async def clear_media(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    data = await _data(state)
    if data["wan_lab_mode"] == "frames":
        await state.update_data(wan_lab_start="", wan_lab_end="")
        await state.set_state(Wan3LabStates.frames)
    else:
        await state.update_data(wan_lab_references=[])
        await state.set_state(Wan3LabStates.references)
    if callback.message:
        await callback.message.edit_text("Очищено. Отправьте новые материалы.", reply_markup=_back())
    await callback.answer()


@router.callback_query(F.data.in_({"admin_wan3:duration", "admin_wan3:ratio", "admin_wan3:resolution"}))
async def choose_option(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    key = (callback.data or "").rsplit(":", 1)[-1]
    data = await _data(state)
    if data["wan_lab_mode"] == "edit" and key in {"duration", "ratio"}:
        await callback.answer("В Edit эти параметры определяет Нейроныч.", show_alert=True)
        return
    values = (
        [str(n) for n in range(2, 31)] if key == "duration"
        else list(NeironychWan3AdminService.RATIOS) if key == "ratio"
        else list(NeironychWan3AdminService.RESOLUTIONS)
    )
    if callback.message:
        await callback.message.edit_text(f"Выберите {html.escape(key)}:", reply_markup=_select_keyboard(key, values))
    await callback.answer()


@router.callback_query(F.data.regexp(r"^admin_wan3:set_(duration|ratio|resolution):"))
async def set_option(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    prefix, value = (callback.data or "").rsplit(":", 1)
    field = prefix.rsplit("_", 1)[-1]
    if field == "duration" and value.isdigit() and 2 <= int(value) <= 30:
        changed = {"wan_lab_duration": int(value)}
    elif field == "ratio" and value in NeironychWan3AdminService.RATIOS:
        changed = {"wan_lab_ratio": value}
    elif field == "resolution" and value in NeironychWan3AdminService.RESOLUTIONS:
        changed = {"wan_lab_resolution": value}
    else:
        await callback.answer("Недопустимый параметр", show_alert=True)
        return
    await state.update_data(**changed)
    await state.set_state(Wan3LabStates.dashboard)
    if callback.message:
        await _show(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "admin_wan3:audio")
async def toggle_audio(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    data = await _data(state)
    await state.update_data(wan_lab_audio=not data["wan_lab_audio"])
    if callback.message:
        await _show(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "admin_wan3:seed")
async def edit_seed(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.set_state(Wan3LabStates.seed)
    if callback.message:
        await callback.message.edit_text("🎲 Введите seed от 0 до 4294967295 или «auto» для случайного.",
                                         reply_markup=_back())
    await callback.answer()


@router.message(Wan3LabStates.seed)
async def receive_seed(message: types.Message, state: FSMContext) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        await state.clear()
        return
    value = str(message.text or "").strip().lower()
    if value in {"auto", "авто", "случайный"}:
        seed = None
    elif value.isascii() and value.isdigit() and 0 <= int(value) <= NeironychWan3AdminService.MAX_SEED:
        seed = int(value)
    else:
        await message.answer("Введите число 0–4294967295 или auto.")
        return
    await state.update_data(wan_lab_seed=seed)
    await state.set_state(Wan3LabStates.dashboard)
    await message.answer("✅ Seed сохранён.", reply_markup=_back())


@router.callback_query(F.data == "admin_wan3:refresh")
async def refresh_model(callback: types.CallbackQuery) -> None:
    if not await _require_admin(callback):
        return
    try:
        enabled = await neironych_wan3_admin_service.list_enabled_wan_models()
    except Exception as exc:
        logger.warning("WAN3 admin catalog unavailable error_type=%s", type(exc).__name__)
        await callback.answer("Не удалось проверить API", show_alert=True)
        return
    await callback.answer("✅ WAN 3.0 доступен" if "wan-3" in enabled else "WAN 3.0 сейчас не доступен",
                          show_alert=True)


@router.callback_query(F.data == "admin_wan3:generate")
async def generate(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    if not callback.message:
        return
    async with _lock(callback.from_user.id):
        data = await _data(state)
        if not neironych_wan3_admin_service.enabled:
            await callback.answer("Ключ Нейроныча не настроен", show_alert=True)
            return
        try:
            payload = _payload(data)
        except (ValueError, TypeError) as exc:
            await callback.answer(str(exc)[:180], show_alert=True)
            return
        if data["wan_lab_last_id"] and data["wan_lab_last_status"] not in {"done", "failed", "expired"}:
            await callback.answer("Предыдущая задача ещё не проверена. Используйте «Проверить».", show_alert=True)
            return
        payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if data["wan_lab_last_id"] and data["wan_lab_last_hash"] == payload_hash:
            await callback.answer("Этот вариант уже запущен. Выберите «Новый запуск».", show_alert=True)
            return
        try:
            enabled = await neironych_wan3_admin_service.list_enabled_wan_models()
            if "wan-3" not in enabled:
                await callback.answer("WAN 3.0 сейчас нет в каталоге Нейроныча", show_alert=True)
                return
        except Exception as exc:
            logger.warning("WAN3 admin submit blocked by catalog error_type=%s", type(exc).__name__)
            await callback.answer("Каталог Нейроныча недоступен — запуск отменён", show_alert=True)
            return
        key = str(data["wan_lab_pending_key"])
        if not key or data["wan_lab_pending_hash"] != payload_hash:
            key = str(uuid.uuid4())
            await state.update_data(wan_lab_pending_key=key, wan_lab_pending_hash=payload_hash)
        await callback.answer("Отправляю запрос…")
        try:
            result = await neironych_wan3_admin_service.submit(payload, idempotency_key=key)
        except (Exception) as exc:  # noqa: BLE001 - unknown acceptance; do NOT generate a fresh key
            logger.warning("WAN3 admin submission uncertain admin_id=%s error_type=%s",
                           callback.from_user.id, type(exc).__name__)
            await callback.message.edit_text(
                "⚠️ Не удалось подтвердить приём WAN 3.0. Запрос может быть принят. "
                "Ключ сохранён: повтор «Запустить» выполнится с тем же Idempotency-Key.",
                reply_markup=_keyboard(data),
            )
            return
        request_id = str(result["request_id"])
        await state.update_data(wan_lab_last_id=request_id, wan_lab_last_hash=payload_hash,
                                wan_lab_last_status="pending", wan_lab_pending_key="", wan_lab_pending_hash="")
        logger.info("WAN3 admin submitted admin_id=%s request_id=%s mode=%s payload_hash=%s",
                    callback.from_user.id, request_id, data["wan_lab_mode"], payload_hash[:12])
        await callback.message.edit_text(
            "⏳ <b>WAN 3.0 через Нейроныча запущен</b>\n"
            f"Request ID: <code>{html.escape(request_id)}</code>\n"
            "Результат придёт сюда. При задержке нажмите «Проверить».",
            reply_markup=_keyboard({**data, "wan_lab_last_id": request_id, "wan_lab_last_status": "pending"}),
            parse_mode="HTML",
        )
        _track(_poll(callback.bot, callback.from_user.id, request_id))


@router.callback_query(F.data == "admin_wan3:check")
async def check(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    data = await _data(state)
    request_id = str(data["wan_lab_last_id"] or "")
    if not request_id:
        await callback.answer("Нет задачи", show_alert=True)
        return
    await callback.answer("Проверяю…")
    try:
        record = await neironych_wan3_admin_service.get_status(request_id)
    except Exception as exc:
        logger.warning("WAN3 admin status lookup error request_id=%s type=%s",
                       request_id, type(exc).__name__)
        if callback.message:
            await callback.message.answer(f"⚠️ Не удалось получить статус {html.escape(request_id)}.",
                                          reply_markup=_keyboard(data))
        return
    status = str(record.get("status") or "unknown").lower()
    await state.update_data(wan_lab_last_status=status)
    if callback.message:
        await callback.message.edit_text(
            f"WAN 3.0: <b>{html.escape(status)}</b>\n"
            f"Request ID: <code>{html.escape(request_id)}</code>",
            reply_markup=_keyboard({**data, "wan_lab_last_status": status}),
            parse_mode="HTML",
        )
    if status == "done":
        try:
            await _deliver(callback.bot, callback.from_user.id, request_id)
        except Exception as exc:
            logger.warning("WAN3 admin delivery failed request_id=%s type=%s", request_id, type(exc).__name__)
            if callback.message:
                await callback.message.answer("⚠️ Видео готово, но отправка не удалась. Нажмите «Проверить» ещё раз.")


@router.callback_query(F.data == "admin_wan3:new")
async def new_request(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    data = await _data(state)
    if data["wan_lab_last_id"]:
        try:
            record = await neironych_wan3_admin_service.get_status(data["wan_lab_last_id"])
            if str(record.get("status") or "").lower() not in {"done", "failed", "expired"}:
                await callback.answer("Задача ещё выполняется. Сначала дождитесь результата.", show_alert=True)
                return
        except Exception:
            await callback.answer("Статус недоступен. Сохраняем ID для восстановления.", show_alert=True)
            return
    await state.update_data(wan_lab_last_id="", wan_lab_last_hash="", wan_lab_last_status="",
                            wan_lab_pending_key="", wan_lab_pending_hash="")
    await state.set_state(Wan3LabStates.dashboard)
    if callback.message:
        await _show(callback.message, state)
    await callback.answer("Готово к новому запуску")
