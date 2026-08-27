from __future__ import annotations

import html
import json
from types import ModuleType
from typing import Any

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.services.rendergrid_service import RenderGridError, rendergrid_client

router = Router(name="rendergrid_test_compat")
_admin_module: ModuleType | None = None


class RenderGridTestStates(StatesGroup):
    waiting_generation_payload = State()
    waiting_creation_id = State()


def _is_admin(user_id: int) -> bool:
    return config.is_admin(user_id)


def _pretty(payload: Any, *, limit: int = 3400) -> str:
    try:
        raw = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        raw = str(payload)
    if len(raw) > limit:
        raw = raw[:limit] + "\n…"
    return f"<pre>{html.escape(raw)}</pre>"


def _menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Баланс", callback_data="rendergrid_test_balance")
    builder.button(text="📦 Модели", callback_data="rendergrid_test_models")
    builder.button(text="⚡ Генерация", callback_data="rendergrid_test_generate")
    builder.button(text="🔎 Creation ID", callback_data="rendergrid_test_creation")
    builder.button(text="⬅️ В админку", callback_data="rendergrid_test_back")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def _result_keyboard(*, has_creation: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_creation:
        builder.button(text="🔄 Проверить статус", callback_data="rendergrid_test_refresh")
    builder.button(text="🧪 RenderGrid", callback_data="admin_rendergrid_test")
    builder.button(text="⬅️ В админку", callback_data="rendergrid_test_back")
    builder.adjust(1)
    return builder.as_markup()


def _provider_error_text(exc: Exception) -> str:
    if isinstance(exc, RenderGridError):
        parts = [f"❌ <b>RenderGrid:</b> {html.escape(str(exc))}"]
        if exc.status is not None:
            parts.append(f"HTTP: <code>{exc.status}</code>")
        if exc.code:
            parts.append(f"Код: <code>{html.escape(exc.code)}</code>")
        if exc.retry_after is not None:
            parts.append(f"Retry-After: <code>{exc.retry_after:g}s</code>")
        if exc.payload:
            parts.append(_pretty(exc.payload, limit=2200))
        return "\n".join(parts)
    return f"❌ <b>Ошибка:</b> {html.escape(str(exc))}"


def _extract_creation_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("id", "creation_id", "task_id"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    nested = payload.get("data")
    if isinstance(nested, dict):
        return _extract_creation_id(nested)
    return None


def _patch_admin_keyboard(admin_module: ModuleType) -> None:
    current = admin_module.get_admin_keyboard
    if getattr(current, "__rendergrid_test_patched__", False):
        return

    def patched_admin_keyboard(*args, **kwargs):
        markup = current(*args, **kwargs)
        rows = [list(row) for row in markup.inline_keyboard]
        test_row = [
            InlineKeyboardButton(
                text="🧪 RenderGrid TEST",
                callback_data="admin_rendergrid_test",
            )
        ]
        insert_at = len(rows)
        if rows and any(button.callback_data == "back_main" for button in rows[-1]):
            insert_at -= 1
        rows.insert(insert_at, test_row)
        return InlineKeyboardMarkup(inline_keyboard=rows)

    patched_admin_keyboard.__rendergrid_test_patched__ = True
    admin_module.get_admin_keyboard = patched_admin_keyboard


def install_rendergrid_test_compat(admin_module: ModuleType) -> None:
    global _admin_module
    _admin_module = admin_module
    _patch_admin_keyboard(admin_module)


@router.callback_query(F.data == "admin_rendergrid_test")
async def rendergrid_test_open(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    await state.clear()
    configured = "✅ задан" if rendergrid_client.configured else "❌ не задан"
    text = (
        "🧪 <b>RenderGrid TEST</b>\n\n"
        "Это изолированная проверка API из Telegram-бота. "
        "Бананы и пользовательские генерации не затрагиваются.\n\n"
        f"API key: <b>{configured}</b>\n"
        f"Base URL: <code>{html.escape(rendergrid_client.base_url)}</code>\n\n"
        "Выберите, что проверить."
    )
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=_menu_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "rendergrid_test_balance")
async def rendergrid_test_balance(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    await callback.answer("Запрашиваю баланс…")
    try:
        payload = await rendergrid_client.get_balance()
        text = "💰 <b>RenderGrid balance</b>\n\n" + _pretty(payload)
    except Exception as exc:
        text = _provider_error_text(exc)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=_result_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "rendergrid_test_models")
async def rendergrid_test_models(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    await callback.answer("Запрашиваю модели…")
    try:
        payload = await rendergrid_client.list_models()
        text = "📦 <b>RenderGrid models</b>\n\n" + _pretty(payload)
    except Exception as exc:
        text = _provider_error_text(exc)
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=_result_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "rendergrid_test_generate")
async def rendergrid_test_generate(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    await state.set_state(RenderGridTestStates.waiting_generation_payload)
    sample = {
        "model": "MODEL_FROM_RENDERGRID",
        "prompt": "A cinematic portrait of a red fox",
        "aspect_ratio": "1:1",
    }
    text = (
        "⚡ <b>Тест генерации RenderGrid</b>\n\n"
        "Пришлите одним сообщением JSON, который нужно отправить в "
        "<code>POST /images/generate</code>. Дополнительные параметры передаются как есть.\n\n"
        "Пример:\n"
        + _pretty(sample, limit=1200)
        + "\n\nДля отмены нажмите кнопку ниже."
    )
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=_result_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.message(RenderGridTestStates.waiting_generation_payload)
async def rendergrid_test_generate_payload(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        await state.clear()
        return
    raw = (message.text or "").strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        await message.answer(
            f"❌ JSON не разобран: <code>{html.escape(str(exc))}</code>",
            reply_markup=_result_keyboard(),
            parse_mode="HTML",
        )
        return
    if not isinstance(payload, dict):
        await message.answer(
            "❌ Нужен JSON-объект, а не массив/строка.",
            reply_markup=_result_keyboard(),
        )
        return

    await message.answer("⏳ Отправляю запрос в RenderGrid…")
    try:
        result = await rendergrid_client.generate_image(payload)
    except Exception as exc:
        await message.answer(
            _provider_error_text(exc),
            reply_markup=_result_keyboard(),
            parse_mode="HTML",
        )
        return

    creation_id = _extract_creation_id(result)
    await state.set_state(None)
    if creation_id:
        await state.update_data(rendergrid_creation_id=creation_id)
    text = "✅ <b>RenderGrid ответил</b>\n\n" + _pretty(result)
    if creation_id:
        text += f"\n\nCreation ID: <code>{html.escape(creation_id)}</code>"
    await message.answer(
        text,
        reply_markup=_result_keyboard(has_creation=bool(creation_id)),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "rendergrid_test_creation")
async def rendergrid_test_creation(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    await state.set_state(RenderGridTestStates.waiting_creation_id)
    if callback.message is not None:
        await callback.message.edit_text(
            "🔎 <b>Проверка creation</b>\n\nПришлите Creation ID одним сообщением.",
            reply_markup=_result_keyboard(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(RenderGridTestStates.waiting_creation_id)
async def rendergrid_test_creation_id(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        await state.clear()
        return
    creation_id = (message.text or "").strip()
    if not creation_id:
        await message.answer("❌ Пустой Creation ID.", reply_markup=_result_keyboard())
        return
    await state.set_state(None)
    await state.update_data(rendergrid_creation_id=creation_id)
    await _send_creation_status(message, creation_id, state)


async def _send_creation_status(
    target: types.Message,
    creation_id: str,
    state: FSMContext,
) -> None:
    try:
        payload = await rendergrid_client.get_creation(creation_id)
        text = "🔎 <b>RenderGrid creation</b>\n\n" + _pretty(payload)
    except Exception as exc:
        text = _provider_error_text(exc)
    await state.update_data(rendergrid_creation_id=creation_id)
    await target.answer(
        text,
        reply_markup=_result_keyboard(has_creation=True),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "rendergrid_test_refresh")
async def rendergrid_test_refresh(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    data = await state.get_data()
    creation_id = str(data.get("rendergrid_creation_id") or "").strip()
    if not creation_id:
        await callback.answer("Creation ID не сохранён", show_alert=True)
        return
    await callback.answer("Проверяю статус…")
    try:
        payload = await rendergrid_client.get_creation(creation_id)
        text = "🔄 <b>RenderGrid status</b>\n\n" + _pretty(payload)
    except Exception as exc:
        text = _provider_error_text(exc)
    if callback.message is not None:
        await callback.message.edit_text(
            text,
            reply_markup=_result_keyboard(has_creation=True),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "rendergrid_test_back")
async def rendergrid_test_back(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    await state.clear()
    admin_module = _admin_module
    if admin_module is None or callback.message is None:
        await callback.answer("Админка недоступна", show_alert=True)
        return
    stats = await admin_module.get_admin_stats()
    subscription_required = await admin_module.is_channel_subscription_required()
    await callback.message.edit_text(
        admin_module._format_admin_panel_text(stats, subscription_required),
        reply_markup=admin_module.get_admin_keyboard(subscription_required),
        parse_mode="HTML",
    )
    await callback.answer()
