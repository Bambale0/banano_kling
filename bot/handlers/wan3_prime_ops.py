"""Authenticated, explicit operator resolution for uncertain Wan submissions."""
from __future__ import annotations

import html
import json
import secrets

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.services.wan3_prime_lifecycle import Wan3PrimeLifecycleError, wan3_prime_lifecycle
from bot.services.wan3_prime_recovery import matches_submission, unresolved_operations

router = Router(name="wan3_prime_ops")


@router.message(Command("wan3_ops"))
async def list_wan_operations(message: types.Message) -> None:
    if not message.from_user or not config.is_admin(message.from_user.id):
        return
    await wan3_prime_lifecycle.init_schema()
    rows = await unresolved_operations(limit=15)
    lines = ["<b>Wan: операции, требующие сверки</b>"]
    for row in rows:
        lines.append(f"<code>{html.escape(row['internal_task_id'])}</code>\n"
                     f"Статус: {html.escape(row['status'])}; резерв: {float(row['reserve_credits']):g}🍌; "
                     f"доставка: {html.escape(str(row['delivery_status'] or 'ожидается'))}")
    if not rows:
        lines.append("Неразрешённых операций нет.")
    lines.append("\nПосле сверки с KIE:\n"
                 "<code>/wan3_resolve ID refund причина</code> — освободить резерв неподтверждённого запуска.\n"
                 "<code>/wan3_resolve ID bind PROVIDER_ID</code> — восстановить только при совпадении параметров у KIE.\n"
                 "Возврат требует отдельного подтверждения; новые генерации не запускаются.")
    await message.answer("\n\n".join(lines), parse_mode="HTML")


@router.message(Command("wan3_resolve"))
async def prepare_wan_resolution(message: types.Message, state: FSMContext) -> None:
    if not message.from_user or not config.is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=3)
    if len(parts) != 4 or parts[2] not in {"refund", "bind"}:
        await message.answer("Используйте /wan3_resolve ID refund причина или /wan3_resolve ID bind PROVIDER_ID")
        return
    task_id, action, argument = parts[1:]
    row = await wan3_prime_lifecycle._intent(task_id)
    if not row or row["status"] != "unknown" or row["provider_task_id"] or row["settled"]:
        await message.answer("Операция не является неподтверждённым запуском. Её состояние и баланс не изменены.")
        return
    if action == "bind":
        canonical = await wan3_prime_lifecycle.transport.get_task_status(argument)
        if not isinstance(canonical, dict) or canonical.get("taskId") != argument or not matches_submission(row, canonical):
            await message.answer("KIE не подтвердил совпадение исходного запроса. Привязка отклонена; проверьте ID в кабинете провайдера.")
            return
    elif not 8 <= len(argument.strip()) <= 1000:
        await message.answer("Укажите результат сверки с провайдером: причина должна содержать 8–1000 символов.")
        return
    token = secrets.token_hex(12)
    await state.update_data(wan3_operator_resolution={"task_id": task_id, "action": action, "argument": argument,
                                                    "admin_id": message.from_user.id, "token": token})
    detail = (f"Возврат резерва {float(row['reserve_credits']):g}🍌.\nПричина: {argument}" if action == "refund"
              else f"Привязка подтверждённой задачи KIE {argument}. Платный запрос не повторяется.")
    await message.answer(f"Операция {task_id}\n{detail}\n\nПодтвердите действие после сверки.", parse_mode=None,
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[
            types.InlineKeyboardButton(text="Подтвердить сверку", callback_data=f"wan3_resolve_confirm:{token}")]]))


@router.callback_query(F.data.startswith("wan3_resolve_confirm:"))
async def confirm_wan_resolution(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Только для администратора", show_alert=True)
        return
    pending = (await state.get_data()).get("wan3_operator_resolution") or {}
    token = str(callback.data).split(":", 1)[1]
    if pending.get("admin_id") != callback.from_user.id or not secrets.compare_digest(str(pending.get("token") or ""), token):
        await callback.answer("Подтверждение устарело. Запросите сверку заново.", show_alert=True)
        return
    task_id = pending["task_id"]
    try:
        if pending["action"] == "refund":
            await wan3_prime_lifecycle.resolve_unknown_refund(task_id, admin_telegram_id=callback.from_user.id, reason=pending["argument"])
        else:
            row = await wan3_prime_lifecycle._intent(task_id)
            canonical = await wan3_prime_lifecycle.transport.get_task_status(pending["argument"])
            if not row or not isinstance(canonical, dict) or not matches_submission(row, canonical):
                raise Wan3PrimeLifecycleError("Параметры задачи не подтверждены", status=409)
            await wan3_prime_lifecycle._bind_provider_id(task_id, pending["argument"])
            from bot import database
            async with database.db_backend.connect(database.DATABASE_PATH) as db:
                await db.execute("INSERT INTO wan3_prime_operator_audit (internal_task_id, admin_telegram_id, action, reason, details) "
                                 "VALUES (?, ?, 'bind', 'canonical provider lineage verified', ?)",
                                 (task_id, callback.from_user.id, json.dumps({"provider_task_id": pending["argument"]})))
                await db.commit()
        current = await wan3_prime_lifecycle._intent(task_id)
        await state.update_data(wan3_operator_resolution=None)
        await callback.message.answer(f"Сверка выполнена. {task_id}\nТекущий статус: {current['status'] if current else 'не найден'}", parse_mode=None)
        await callback.answer()
    except (Wan3PrimeLifecycleError, ValueError) as exc:
        await callback.answer(str(exc)[:180], show_alert=True)
