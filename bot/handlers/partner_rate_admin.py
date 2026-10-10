"""Admin-only first-line partner percentages with expiring FSM confirmation."""
from __future__ import annotations

import asyncio
import html
import logging
import math
import secrets
import time
from decimal import Decimal, InvalidOperation, localcontext
from weakref import WeakValueDictionary

from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.config import config
from bot.partner_commission_settings import (
    PartnerCommissionConflict,
    get_partner_commission_setting,
    set_partner_commission_percent,
)

logger = logging.getLogger(__name__)
router = Router(name="partner_rate_admin")
PREFIX = "admin_rate"  # Unique: promo_admin has existing admin_pr:* callbacks.
SCREEN_TTL_SECONDS = 10 * 60
_LOCKS: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()


class PartnerRateAdminStates(StatesGroup):
    user_id = State()
    percent = State()
    confirmation = State()


def _lock(actor_id):
    lock = _LOCKS.get(actor_id)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[actor_id] = lock
    return lock


def _cb(action, token, *values):
    return ":".join([PREFIX, action, *map(str, values), token])


def _button(text, data):
    if len(data.encode("utf-8")) > 64:
        raise ValueError("Partner rate callback is too long")
    return types.InlineKeyboardButton(text=text, callback_data=data)


def _percent(value):
    return str(float(value)).removesuffix(".0") + "%"


def _snapshot(setting):
    return {key: setting[key] for key in (
        "telegram_id", "effective_percent", "override_percent", "revision", "source",
    )}


async def _authorized(event):
    if event.from_user and config.is_admin(event.from_user.id):
        return True
    if hasattr(event, "data"):
        await event.answer("⛔ Нет доступа", show_alert=True)
    else:
        await event.answer("⛔ Нет доступа")
    return False


async def _present(event, text, rows, *, fresh=False):
    kwargs = {
        "parse_mode": "HTML",
        "reply_markup": types.InlineKeyboardMarkup(inline_keyboard=rows),
    }
    if not hasattr(event, "data"):
        return await event.answer(text, **kwargs)
    if event.message is None or not hasattr(event.message, "edit_text"):
        return await event.bot.send_message(event.from_user.id, text, **kwargs)
    if fresh:
        return await event.message.answer(text, **kwargs)
    try:
        return await event.message.edit_text(text, **kwargs)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return event.message
    return await event.message.answer(text, **kwargs)


async def _screen(event, state, **values):
    token = secrets.token_hex(8)
    await state.clear()
    await state.update_data(
        partner_rate_token=token,
        partner_rate_actor=event.from_user.id,
        partner_rate_expires_at=time.time() + SCREEN_TTL_SECONDS,
        **values,
    )
    return token


def _expired(data):
    expiry = data.get("partner_rate_expires_at")
    return not isinstance(expiry, (int, float)) or not math.isfinite(expiry) or time.time() >= expiry


def _back(token):
    return [_button("🔙 Проценты партнёров", _cb("home", token))]


async def _home(event, state, notice=""):
    token = await _screen(event, state)
    text = (
        "🤝 <b>Проценты партнёров · первая линия</b>\n\n"
        "Базовая ставка — 30%. Индивидуальная ставка назначается по Telegram ID.\n"
        "40% назначается только вручную, без автоматического повышения.\n"
        "0% отключает только начисления первой линии. Вторая линия и награда за повторы независимы.\n"
        "Новая ставка действует для будущих счетов; уже созданные счета и начисления сохраняются."
    )
    if notice:
        text += "\n\n" + html.escape(notice)
    await _present(event, text, [
        [_button("👤 Найти по Telegram ID", _cb("lookup", token))],
        [_button("🔙 К партнёрам", "admin_partners")],
    ])


async def _view(event, state, target, notice=""):
    setting = await get_partner_commission_setting(target)
    if setting is None:
        return await _home(event, state, "Пользователь не найден. Сначала он должен открыть бота или Mini App.")
    token = await _screen(event, state, partner_rate_snapshot=_snapshot(setting))
    name = setting.get("username") or setting.get("first_name") or "—"
    source = {
        "admin": "назначена администратором",
        "configuration": "индивидуальная настройка конфигурации",
        "default": "базовая ставка",
    }.get(setting["source"], "текущая настройка")
    text = (
        f"👤 <b>{html.escape(str(name))}</b>\nTelegram ID: <code>{target}</code>\n\n"
        f"Первая линия: <b>{_percent(setting['effective_percent'])}</b>\n"
        f"Источник: {source}\n\n"
        "Выберите новую ставку. Изменение сохранится только после подтверждения.\n"
        "0% отключает только первую линию. Вторая линия и награда за повторы независимы."
    )
    if notice:
        text += "\n\n" + html.escape(notice)
    await _present(event, text, [
        [_button(f"{value}%", _cb("quick", token, value)) for value in (0, 30, 40)],
        [_button("✏️ Другой процент", _cb("custom", token))],
        [_button("🔄 Обновить", _cb("view", token))],
        _back(token),
    ])


async def _current_or_refresh(event, state, snapshot):
    if not isinstance(snapshot, dict) or "telegram_id" not in snapshot:
        raise ValueError("Откройте карточку партнёра заново.")
    target = snapshot["telegram_id"]
    current = await get_partner_commission_setting(target)
    if current is None or _snapshot(current) != snapshot:
        await _view(event, state, target, "Ставка уже изменилась. Проверьте её и выберите процент заново.")
        return False
    return True


async def _confirmation(event, state, snapshot, percent):
    if not await _current_or_refresh(event, state, snapshot):
        return
    token = await _screen(
        event, state, partner_rate_snapshot=snapshot,
        partner_rate_pending={"percent": percent, "snapshot": snapshot},
    )
    await state.set_state(PartnerRateAdminStates.confirmation)
    await _present(event, (
        f"Назначить ставку первой линии для Telegram ID <code>{snapshot['telegram_id']}</code>?\n\n"
        f"Сейчас: <b>{_percent(snapshot['effective_percent'])}</b>\n"
        f"Новая ставка: <b>{_percent(percent)}</b>\n\n"
        "Ставка будет закреплена за этим партнёром.\n"
        "Вторая линия и награда за повторы не меняются. 0% отключает только первую линию.\n"
        "Изменение действует для будущих счетов. Уже созданные счета и начисления сохраняются."
    ), [
        [_button("✅ Подтвердить", _cb("confirm", token))],
        [_button("❌ Отмена", _cb("cancel", token))],
    ])


@router.callback_query(F.data == "admin_partner_rates")
async def open_partner_rates(callback: types.CallbackQuery, state: FSMContext):
    if not await _authorized(callback):
        return
    async with _lock(callback.from_user.id):
        await _home(callback, state)
    await callback.answer()


async def _handle_callback(callback, state, data, parts):
    action, args = parts[1], parts[2:-1]
    snapshot = data.get("partner_rate_snapshot")
    if action == "home" and not args:
        return await _home(callback, state)
    if action == "lookup" and not args:
        token = await _screen(callback, state)
        await state.set_state(PartnerRateAdminStates.user_id)
        prompt = await _present(callback, "Введите Telegram ID существующего пользователя (только цифры):", [_back(token)], fresh=True)
        return await state.update_data(partner_rate_prompt_id=getattr(prompt, "message_id", 0))
    if action in {"view", "cancel"} and not args and snapshot:
        return await _view(callback, state, snapshot["telegram_id"])
    if action == "quick" and len(args) == 1 and args[0] in {"0", "30", "40"}:
        return await _confirmation(callback, state, snapshot, float(args[0]))
    if action == "custom" and not args:
        if not await _current_or_refresh(callback, state, snapshot):
            return
        token = await _screen(callback, state, partner_rate_snapshot=snapshot)
        await state.set_state(PartnerRateAdminStates.percent)
        prompt = await _present(callback, (
            "Введите процент первой линии от 0 до 100, максимум 2 знака после запятой.\n"
            "0 отключает только первую линию. После ввода потребуется подтверждение."
        ), [[_button("❌ Отмена", _cb("cancel", token))]], fresh=True)
        return await state.update_data(partner_rate_prompt_id=getattr(prompt, "message_id", 0))
    if action == "confirm" and not args:
        pending = data.get("partner_rate_pending")
        if await state.get_state() != PartnerRateAdminStates.confirmation.state or not pending:
            raise ValueError("Подтверждение уже закрыто.")
        # Consume the nonce before awaiting any mutation. The service additionally
        # checks the stored revision atomically, including across admin sessions.
        await state.clear()
        snapshot = pending["snapshot"]
        if not await _current_or_refresh(callback, state, snapshot):
            return
        if _expired(data):
            raise ValueError("Время подтверждения истекло. Откройте проценты партнёров заново.")
        try:
            result = await set_partner_commission_percent(
                callback.from_user.id, snapshot["telegram_id"], pending["percent"],
                expected_revision=snapshot["revision"],
            )
        except PartnerCommissionConflict:
            return await _view(callback, state, snapshot["telegram_id"], "Ставка уже изменилась. Проверьте её и выберите процент заново.")
        notice = "Ставка сохранена." if result["changed"] else "Эта индивидуальная ставка уже назначена."
        return await _view(callback, state, snapshot["telegram_id"], notice)
    raise ValueError("Кнопка устарела. Откройте проценты партнёров заново.")


@router.callback_query(F.data.startswith(f"{PREFIX}:"))
async def partner_rate_callback(callback: types.CallbackQuery, state: FSMContext):
    if not await _authorized(callback):
        return
    async with _lock(callback.from_user.id):
        data = await state.get_data()
        parts = str(callback.data or "").split(":")
        token = data.get("partner_rate_token", "")
        if (
            len(parts) < 3 or parts[0] != PREFIX or not token
            or data.get("partner_rate_actor") != callback.from_user.id
            or not secrets.compare_digest(parts[-1].encode(), token.encode())
        ):
            return await callback.answer("Кнопка устарела. Откройте проценты партнёров заново.", show_alert=True)
        if _expired(data):
            await state.clear()
            return await callback.answer("Время подтверждения истекло. Откройте проценты партнёров заново.", show_alert=True)
        try:
            await _handle_callback(callback, state, data, parts)
        except (ValueError, PermissionError) as exc:
            return await callback.answer(str(exc)[:190], show_alert=True)
        except Exception:
            logger.exception("Partner rate admin operation failed actor=%s", callback.from_user.id)
            await _home(callback, state, "Не удалось завершить операцию. Проверьте текущую ставку перед повтором.")
    await callback.answer()


@router.message(StateFilter(PartnerRateAdminStates), F.text.startswith("/"))
async def leave_partner_rates_for_command(message: types.Message, state: FSMContext):
    if not await _authorized(message):
        return
    async with _lock(message.from_user.id):
        await state.clear()
    # Keep normal /admin, /start and other command behavior in later routers.
    raise SkipHandler


@router.message(PartnerRateAdminStates.user_id, F.text, ~F.text.startswith("/"))
@router.message(PartnerRateAdminStates.percent, F.text, ~F.text.startswith("/"))
async def partner_rate_message(message: types.Message, state: FSMContext):
    if not await _authorized(message):
        return
    async with _lock(message.from_user.id):
        data = await state.get_data()
        if data.get("partner_rate_actor") != message.from_user.id:
            return
        if _expired(data):
            await state.clear()
            return await message.answer("Время ввода истекло. Откройте проценты партнёров заново.")
        prompt_id = data.get("partner_rate_prompt_id", 0)
        reply = getattr(message, "reply_to_message", None)
        if message.message_id <= prompt_id or (reply is not None and reply.message_id != prompt_id):
            return
        value = (message.text or "").strip()
        current_state = await state.get_state()
        try:
            if current_state == PartnerRateAdminStates.user_id.state:
                if not value.isascii() or not value.isdigit() or len(value) > 19 or not 0 < int(value) < 2**63:
                    return await message.answer("Нужен положительный Telegram ID, только цифры.")
                return await _view(message, state, int(value))
            if current_state != PartnerRateAdminStates.percent.state:
                return
            try:
                number = Decimal(value.replace(",", ".")) if len(value) <= 128 else Decimal("NaN")
                if not number.is_finite() or not 0 <= number <= 100:
                    raise ValueError
                with localcontext() as decimal_context:
                    decimal_context.prec = 256  # Input length is bounded to 128 characters.
                    if number != number.quantize(Decimal("0.01")):
                        raise ValueError
                percent = float(number)
            except (ValueError, InvalidOperation):
                return await message.answer("Введите число от 0 до 100, не более двух знаков после запятой. Например: 30 или 12,5.")
            await _confirmation(message, state, data.get("partner_rate_snapshot"), percent)
        except (ValueError, PermissionError) as exc:
            await message.answer(str(exc))
        except Exception:
            logger.exception("Partner rate admin input failed actor=%s", message.from_user.id)
            await _home(message, state, "Не удалось завершить операцию. Проверьте текущую ставку перед повтором.")
