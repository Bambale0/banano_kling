from __future__ import annotations

from aiogram import F, Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.services.partner_approval_service import review_partner_application

user_router = Router()
admin_router = Router()


async def _render_partner_entry(target: types.Message, telegram_id: int) -> None:
    from bot.handlers.common import render_partner_program

    await render_partner_program(target, user_id=telegram_id)


@user_router.message(Command("ref", "earn", "partner"), StateFilter(None))
async def partner_command(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    await _render_partner_entry(message, message.from_user.id)


@user_router.callback_query(F.data.in_({"menu_referrals", "menu_partner"}))
async def partner_menu(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _render_partner_entry(callback.message, callback.from_user.id)
    await callback.answer()


@user_router.callback_query(F.data == "partner_stats")
async def partner_stats_gate(callback: types.CallbackQuery) -> None:
    """Keep old statistics buttons working for every account."""

    from bot.handlers.common import partner_stats

    await partner_stats(callback)


@user_router.callback_query(F.data == "partner_accept")
async def partner_application_submit(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Old activation buttons now open the cabinet without recording consent."""

    await state.clear()
    await _render_partner_entry(callback.message, callback.from_user.id)
    await callback.answer("Партнёрская программа доступна всем пользователям")


async def _review_application(
    callback: types.CallbackQuery,
    *,
    application_id: int,
    approve: bool,
) -> None:
    if not config.is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    result = await review_partner_application(
        application_id,
        approve=approve,
        admin_telegram_id=callback.from_user.id,
    )
    reason = str(result.get("reason") or "")
    if reason == "not_found":
        await callback.answer("Заявка не найдена", show_alert=True)
    elif reason == "activation_not_required":
        await callback.answer(
            "Активация больше не требуется. Партнёрская программа доступна всем; заявка сохранена в истории.",
            show_alert=True,
        )
    else:
        await callback.answer("Не удалось открыть заявку", show_alert=True)


@admin_router.callback_query(F.data.startswith("partner_app_approve_"))
async def approve_partner_application_callback(callback: types.CallbackQuery) -> None:
    try:
        application_id = int(callback.data.rsplit("_", 1)[1])
    except (TypeError, ValueError):
        await callback.answer("Некорректный ID заявки", show_alert=True)
        return
    await _review_application(callback, application_id=application_id, approve=True)


@admin_router.callback_query(F.data.startswith("partner_app_reject_"))
async def reject_partner_application_callback(callback: types.CallbackQuery) -> None:
    try:
        application_id = int(callback.data.rsplit("_", 1)[1])
    except (TypeError, ValueError):
        await callback.answer("Некорректный ID заявки", show_alert=True)
        return
    await _review_application(callback, application_id=application_id, approve=False)
