"""Config-admin-only creator tariff editor with expiring FSM confirmations."""
from __future__ import annotations

import asyncio
import copy
import html
import json
import logging
import math
import secrets
from weakref import WeakValueDictionary

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot import db as db_backend
from bot.config import config
from bot.creator_tariff import creator_tariff_status, validate_creator_tariff_config
from bot.creator_tariff_membership import (
    get_creator_tariff_membership,
    record_creator_tariff_config_audit,
    set_creator_tariff_membership,
)
from bot.services.preset_manager import preset_manager

logger = logging.getLogger(__name__)
router = Router(name="creator_tariff_admin")
PREFIX = "admin_ct"
_LOCKS: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()
_CONFIG_LOCK = asyncio.Lock()
MODEL_LABELS = {"seedance_2": "Seedance 2.0", "seedance_2_5": "Seedance 2.5"}


class CreatorTariffAdminStates(StatesGroup):
    user_id = State()
    price = State()
    confirmation = State()


class CreatorTariffConfigConflict(ValueError):
    """The configuration changed after the administrator opened this editor."""


def _lock(actor_id):
    lock = _LOCKS.get(actor_id)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[actor_id] = lock
    return lock


def _button(text, data):
    if len(data.encode("utf-8")) > 64:
        raise ValueError("Creator tariff callback is too long")
    return types.InlineKeyboardButton(text=text, callback_data=data)


def _keyboard(rows):
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _cb(action, token, *values):
    return ":".join([PREFIX, action, *map(str, values), token])


def _raw_tariff():
    raw = preset_manager.get_price_config().get("creator_tariff", {})
    return copy.deepcopy(raw if isinstance(raw, dict) else {})


def _fingerprint(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


async def _authorized(event):
    if event.from_user and config.is_admin(event.from_user.id):
        return True
    if hasattr(event, "data"):
        await event.answer("⛔ Нет доступа", show_alert=True)
    else:
        await event.answer("⛔ Нет доступа")
    return False


async def _present(event, text, rows, *, fresh=False):
    kwargs = {"parse_mode": "HTML", "reply_markup": _keyboard(rows)}
    if hasattr(event, "data"):
        if event.message is None:
            return await event.bot.send_message(event.from_user.id, text, **kwargs)
        if fresh:
            return await event.message.answer(text, **kwargs)
        try:
            return await event.message.edit_text(text, **kwargs)
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return event.message
        return await event.message.answer(text, **kwargs)
    return await event.answer(text, **kwargs)


async def _screen(state, **values):
    token = secrets.token_hex(4)
    await state.clear()
    await state.update_data(creator_token=token, **values)
    return token


def _back(token):
    return [_button("🔙 Тариф креатора", _cb("home", token))]


async def _home(event, state, notice=""):
    status = creator_tariff_status()
    token = await _screen(state)
    active = bool(status["enabled"] and status["configured"])
    text = (
        "🎬 <b>Тариф креатора · Seedance</b>\n\n"
        f"Статус: <b>{'включён' if active else 'выключен'}</b>\n"
        "Доступ назначается отдельно по Telegram ID. Права администратора и баланс не меняются.\n"
        "Цены задаются отдельно для каждой модели и качества. Видео-референс: ×2.\n"
    )
    if not active:
        text += "\nСейчас применяется обычная цена, даже для назначенных креаторов.\n"
    if not status["configured"]:
        text += "\nДля включения заполните все цены в разделе «Цены креатора».\n"
    if status.get("errors"):
        text += "\n" + "\n".join(html.escape(str(error)) for error in status["errors"])
    if notice:
        text += "\n\n" + html.escape(notice)
    await _present(event, text, [
        [_button("👤 Найти пользователя по ID", _cb("lookup", token))],
        [_button("💰 Цены креатора", _cb("prices", token))],
        [_button("⏸ Выключить…" if status["enabled"] else "▶️ Включить…", _cb("toggle", token, int(not status["enabled"])))],
        [_button("🔙 Разделы цен", "admin_prices")],
    ])


async def _lookup_user(telegram_id):
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        row = await (await db.execute(
            "SELECT telegram_id, username, first_name FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )).fetchone()
    return dict(row) if row else None


async def _member_view(event, state, telegram_id, notice=""):
    user = await _lookup_user(telegram_id)
    if user is None:
        return await _home(event, state, "Пользователь не найден. Сначала он должен открыть бота или Mini App.")
    enabled = await get_creator_tariff_membership(telegram_id)
    token = await _screen(state, creator_target=telegram_id, creator_member_enabled=enabled)
    status = creator_tariff_status()
    name = user.get("username") or user.get("first_name") or "—"
    text = (
        f"👤 <b>{html.escape(str(name))}</b>\nTelegram ID: <code>{telegram_id}</code>\n\n"
        f"Тариф креатора: <b>{'назначен' if enabled else 'не назначен'}</b>\n"
        "Права администратора и баланс не меняются."
    )
    if not (status["enabled"] and status["configured"]):
        text += "\nТариф выключен или не настроен: пока действует обычная цена."
    if config.is_admin(telegram_id):
        text += "\nДля этого администратора сохраняется существующий бесплатный режим."
    if notice:
        text += "\n\n" + html.escape(notice)
    await _present(event, text, [
        [_button("🚫 Отозвать доступ…" if enabled else "➕ Назначить доступ…", _cb("member", token, telegram_id, int(not enabled)))],
        [_button("🔄 Обновить", _cb("view", token, telegram_id))],
        _back(token),
    ])


async def _prices(event, state, notice=""):
    status = creator_tariff_status()
    raw = _raw_tariff()
    token = await _screen(state, creator_config_fingerprint=_fingerprint(raw))
    lines = ["💰 <b>Цены креатора</b>", "Отдельные ставки в 🍌/сек, без видео-референса. С видео-референсом ×2.", ""]
    rows = []
    for model, qualities in status["required_qualities"].items():
        model_data = status["video_models"].get(model, {})
        rates = model_data.get("quality_costs", {})
        for quality in qualities:
            rate = rates.get(quality)
            label = f"{MODEL_LABELS.get(model, model)} · {quality}"
            value = f"{rate:g} 🍌/сек" if isinstance(rate, (int, float)) and not isinstance(rate, bool) and math.isfinite(rate) and rate > 0 else "не задано"
            lines.append(f"{html.escape(label)}: <b>{value}</b>")
            rows.append([_button(f"✏️ {label}", _cb("rate", token, model, quality))])
    if not (status["enabled"] and status["configured"]):
        lines.extend(["", "Пока тариф выключен или не заполнен, действует обычная цена."])
    if notice:
        lines.extend(["", html.escape(notice)])
    rows.append(_back(token))
    await _present(event, "\n".join(lines), rows)


async def save_creator_tariff_config(actor_id, raw, *, expected_fingerprint):
    """Preserve ordinary prices and audit the intent before writing the file.

    Config file and database cannot share a transaction. Immutable requested /
    result events make an interrupted write distinguishable from completion.
    """
    if type(actor_id) is not int or not config.is_admin(actor_id):
        raise PermissionError("Creator tariff changes require administrator access")
    async with _CONFIG_LOCK:
        full = preset_manager.get_price_config()
        before = full.get("creator_tariff", {})
        if _fingerprint(before) != expected_fingerprint:
            raise CreatorTariffConfigConflict("Цены уже изменились. Откройте раздел заново.")
        after = validate_creator_tariff_config(raw)
        if before == after:
            return after
        await record_creator_tariff_config_audit(actor_id, before, after, event_type="config_change_requested")
        # An unrelated ordinary-price edit may have happened while audit I/O
        # yielded. Re-read immediately before the synchronous write so it is
        # never reverted by this editor's older whole-file snapshot.
        full = preset_manager.get_price_config()
        if _fingerprint(full.get("creator_tariff", {})) != expected_fingerprint:
            raise CreatorTariffConfigConflict("Цены уже изменились. Откройте раздел заново.")
        after = validate_creator_tariff_config(raw)
        full["creator_tariff"] = after
        if not preset_manager.update_price_config(full):
            await record_creator_tariff_config_audit(actor_id, before, after, event_type="config_update_failed")
            raise RuntimeError("Не удалось перезагрузить цены. Проверьте конфигурацию перед повтором.")
        logger.info("creator_tariff_config_updated actor=%s before=%s after=%s", actor_id, _fingerprint(before), _fingerprint(after))
        await record_creator_tariff_config_audit(actor_id, before, after)
        return after


@router.callback_query(F.data == "admin_creator_tariff")
async def open_creator_tariff(callback: types.CallbackQuery, state: FSMContext):
    if not await _authorized(callback):
        return
    async with _lock(callback.from_user.id):
        await _home(callback, state)
    await callback.answer()


async def _confirmation(event, state, pending, text):
    token = await _screen(state, creator_pending=pending)
    await state.set_state(CreatorTariffAdminStates.confirmation)
    await _present(event, text, [
        [_button("✅ Подтвердить", _cb("confirm", token))],
        [_button("❌ Отмена", _cb("home", token))],
    ])


async def _handle_callback(callback, state, data, parts):
    action, args = parts[1], parts[2:-1]
    if action == "home" and not args:
        return await _home(callback, state)
    if action == "lookup" and not args:
        token = await _screen(state)
        await state.set_state(CreatorTariffAdminStates.user_id)
        prompt = await _present(callback, "Введите Telegram ID существующего пользователя (только цифры):", [_back(token)], fresh=True)
        return await state.update_data(creator_prompt_id=getattr(prompt, "message_id", 0))
    if action == "prices" and not args:
        return await _prices(callback, state)
    if action == "view" and len(args) == 1 and args[0].isdigit():
        target = int(args[0])
        if target != data.get("creator_target"):
            raise ValueError("Пользователь не совпадает с открытой карточкой.")
        return await _member_view(callback, state, target)
    if action == "member" and len(args) == 2 and args[0].isdigit() and args[1] in {"0", "1"}:
        target, enabled = int(args[0]), args[1] == "1"
        if target != data.get("creator_target") or enabled == data.get("creator_member_enabled"):
            raise ValueError("Пользователь или действие не совпадает с открытой карточкой.")
        current = await get_creator_tariff_membership(target)
        if current != data["creator_member_enabled"]:
            return await _member_view(callback, state, target, "Доступ уже изменён. Проверьте текущее состояние.")
        return await _confirmation(callback, state, {"kind": "member", "target": target, "enabled": enabled, "before": current},
            f"{'Назначить' if enabled else 'Отозвать'} тариф креатора для Telegram ID <code>{target}</code>?\nПрава администратора и баланс не меняются.")
    if action == "toggle" and len(args) == 1 and args[0] in {"0", "1"}:
        raw = _raw_tariff()
        enabled = args[0] == "1"
        if bool(raw.get("enabled", False)) == enabled:
            return await _home(callback, state, "Статус тарифа уже изменился.")
        candidate = copy.deepcopy(raw)
        candidate["enabled"] = enabled
        validate_creator_tariff_config(candidate)
        return await _confirmation(callback, state, {"kind": "config", "candidate": candidate, "fingerprint": _fingerprint(raw)},
            "Включить тариф креатора для всех назначенных пользователей?" if enabled else "Выключить тариф креатора? Назначенные пользователи вернутся к обычной цене.")
    if action == "rate" and len(args) == 2:
        model, quality = args
        status = creator_tariff_status()
        if quality not in status["required_qualities"].get(model, []):
            raise ValueError("Неизвестная модель или качество.")
        expected = data.get("creator_config_fingerprint")
        if expected != _fingerprint(_raw_tariff()):
            raise CreatorTariffConfigConflict("Цены уже изменились. Откройте раздел заново.")
        token = await _screen(state, creator_model=model, creator_quality=quality, creator_config_fingerprint=expected)
        await state.set_state(CreatorTariffAdminStates.price)
        prompt = await _present(callback, f"Введите цену {html.escape(MODEL_LABELS.get(model, model))} · {html.escape(quality)} в 🍌/сек.\nТолько положительное число; видео-референс автоматически ×2.", [_back(token)], fresh=True)
        return await state.update_data(creator_prompt_id=getattr(prompt, "message_id", 0))
    if action == "confirm" and not args:
        pending = data.get("creator_pending", {})
        if await state.get_state() != CreatorTariffAdminStates.confirmation.state:
            raise ValueError("Подтверждение уже закрыто.")
        # Consume before awaiting a mutation so repeated clicks cannot repeat it.
        await state.clear()
        if pending.get("kind") == "member":
            current = await get_creator_tariff_membership(pending["target"])
            if current != pending["before"]:
                return await _member_view(callback, state, pending["target"], "Доступ уже изменён. Проверьте текущее состояние.")
            await set_creator_tariff_membership(callback.from_user.id, pending["target"], pending["enabled"], expected_enabled=pending["before"])
            return await _member_view(callback, state, pending["target"], "Доступ сохранён.")
        if pending.get("kind") == "config":
            await save_creator_tariff_config(callback.from_user.id, pending["candidate"], expected_fingerprint=pending["fingerprint"])
            return await _home(callback, state, "Настройки сохранены.")
    raise ValueError("Кнопка устарела. Откройте раздел тарифа заново.")


@router.callback_query(F.data.startswith(f"{PREFIX}:"))
async def creator_tariff_callback(callback: types.CallbackQuery, state: FSMContext):
    if not await _authorized(callback):
        return
    async with _lock(callback.from_user.id):
        data = await state.get_data()
        parts = str(callback.data or "").split(":")
        token = data.get("creator_token", "")
        if len(parts) < 3 or not token or not secrets.compare_digest(parts[-1], token):
            return await callback.answer("Кнопка устарела. Откройте тариф заново.", show_alert=True)
        try:
            await _handle_callback(callback, state, data, parts)
        except (ValueError, PermissionError) as exc:
            return await callback.answer(str(exc)[:190], show_alert=True)
        except Exception:
            logger.exception("Creator tariff admin operation failed actor=%s", callback.from_user.id)
            await _home(callback, state, "Не удалось завершить операцию. Проверьте текущее состояние перед повтором.")
    await callback.answer()


@router.message(CreatorTariffAdminStates.user_id)
@router.message(CreatorTariffAdminStates.price)
async def creator_tariff_message(message: types.Message, state: FSMContext):
    if not await _authorized(message):
        return
    async with _lock(message.from_user.id):
        data = await state.get_data()
        if message.message_id <= data.get("creator_prompt_id", 0):
            return
        raw_value = (message.text or "").strip()
        current_state = await state.get_state()
        if current_state == CreatorTariffAdminStates.user_id.state:
            if not raw_value.isascii() or not raw_value.isdigit() or len(raw_value) > 19 or not 0 < int(raw_value) < 2**63:
                return await message.answer("Нужен положительный Telegram ID, только цифры.")
            return await _member_view(message, state, int(raw_value))
        if current_state != CreatorTariffAdminStates.price.state:
            return
        try:
            price = float(raw_value.replace(",", "."))
            if not math.isfinite(price) or price <= 0:
                raise ValueError("Цена должна быть положительным конечным числом.")
            model, quality = data["creator_model"], data["creator_quality"]
            if quality not in creator_tariff_status()["required_qualities"].get(model, []):
                raise ValueError("Модель или качество изменились. Откройте раздел цен заново.")
            candidate = _raw_tariff()
            candidate.setdefault("enabled", False)
            candidate.setdefault("video_models", {}).setdefault(model, {}).setdefault("quality_costs", {})[quality] = price
            await save_creator_tariff_config(message.from_user.id, candidate, expected_fingerprint=data["creator_config_fingerprint"])
        except (ValueError, PermissionError) as exc:
            return await message.answer(str(exc))
        except Exception:
            logger.exception("Creator tariff price save failed actor=%s", message.from_user.id)
            return await _prices(message, state, "Не удалось завершить сохранение. Проверьте текущие цены перед повтором.")
        await _prices(message, state, "Цена сохранена. Остальные ставки не изменены.")
