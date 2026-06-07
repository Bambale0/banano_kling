"""Separate admin router for referral, partner, and anti-fraud settings."""

from __future__ import annotations

import html

from aiogram import F, Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.database import get_admin_partner_summaries
from bot.services.referral_admin_config import (
    PartnerPayout,
    ReferralAdminConfig,
    ReferralAdminConfigService,
    referral_admin_config_service,
)


router = Router()


class ReferralAdminStates(StatesGroup):
    waiting_referrer_bonus = State()
    waiting_friend_bonus = State()
    waiting_daily_limit = State()


def _is_admin(user_id: int) -> bool:
    return config.is_admin(user_id)


def _service() -> ReferralAdminConfigService:
    return referral_admin_config_service


def _settings_keyboard(config_data: ReferralAdminConfig) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Бонус пригласившему", callback_data="admin_ref:set_referrer_bonus")
    builder.button(text="Бонус другу", callback_data="admin_ref:set_friend_bonus")
    trigger_text = "Начислять: регистрация" if config_data.bonus_trigger == "signup" else "Начислять: первая оплата"
    next_trigger = "first_payment" if config_data.bonus_trigger == "signup" else "signup"
    builder.button(text=trigger_text, callback_data=f"admin_ref:trigger:{next_trigger}")
    builder.button(text="Дневной лимит", callback_data="admin_ref:set_daily_limit")
    builder.button(text="Антифрод", callback_data="admin_ref:antifraud")
    builder.button(text="Партнёры", callback_data="admin_ref:partner_summary")
    builder.button(text="Выплаты", callback_data="admin_ref:payouts")
    builder.button(text="Назад в админку", callback_data="admin_back")
    builder.adjust(1)
    return builder.as_markup()


def _back_keyboard(callback_data: str = "admin_ref:menu") -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data=callback_data)
    builder.adjust(1)
    return builder.as_markup()


def _antifraud_keyboard(config_data: ReferralAdminConfig) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for rule in config_data.antifraud_rules:
        mark = "Вкл" if rule.enabled else "Выкл"
        builder.button(text=f"{mark}: {rule.title}", callback_data=f"admin_ref:rule:{rule.key}")
    builder.button(text="Назад", callback_data="admin_ref:menu")
    builder.adjust(1)
    return builder.as_markup()


def _format_config(config_data: ReferralAdminConfig) -> str:
    trigger = "при регистрации" if config_data.bonus_trigger == "signup" else "после первой оплаты"
    enabled_rules = sum(1 for rule in config_data.antifraud_rules if rule.enabled)
    return (
        "<b>Реферальная программа</b>\n\n"
        f"Бонус пригласившему: <b>{config_data.referrer_bonus_credits}</b> BoomCoin\n"
        f"Бонус другу: <b>{config_data.friend_bonus_credits}</b> BoomCoin\n"
        f"Когда начислять: <b>{trigger}</b>\n"
        f"Дневной лимит: <b>{config_data.daily_referral_limit}</b>\n"
        f"Антифрод-правил включено: <b>{enabled_rules}/{len(config_data.antifraud_rules)}</b>"
    )


def _format_antifraud(config_data: ReferralAdminConfig) -> str:
    lines = ["<b>Антифрод-правила</b>"]
    for rule in config_data.antifraud_rules:
        status = "включено" if rule.enabled else "выключено"
        lines.append(
            f"\n<b>{rule.title}</b>\n"
            f"Статус: {status}\n"
            f"Порог: {rule.threshold}, окно: {rule.window_hours} ч, действие: {rule.action}"
        )
    return "\n".join(lines)


def _format_partner_name(summary: dict) -> str:
    username = str(summary.get("username") or "").strip()
    if username:
        return f"@{html.escape(username)}"
    full_name = " ".join(
        part for part in (
            str(summary.get("first_name") or "").strip(),
            str(summary.get("last_name") or "").strip(),
        )
        if part
    )
    if full_name:
        return html.escape(full_name)
    return f"ID {html.escape(str(summary.get('telegram_id') or ''))}"


def _format_partner_summaries(summaries: list[dict], bot_username: str | None = None) -> str:
    if not summaries:
        return (
            "<b>Партнёры</b>\n\n"
            "Пока нет пользователей с активированным партнёрским статусом."
        )

    lines = ["<b>Партнёры</b>"]
    for index, summary in enumerate(summaries, start=1):
        referral_code = str(summary.get("referral_code") or "").strip()
        referral_link = (
            f"https://t.me/{bot_username}?start=ref_{referral_code}"
            if bot_username and referral_code
            else ""
        )
        lines.append(
            "\n"
            f"{index}. <b>{_format_partner_name(summary)}</b> "
            f"· <code>{html.escape(str(summary.get('telegram_id') or ''))}</code>\n"
            f"Пришло пользователей: <b>{int(summary.get('users_count') or 0)}</b>\n"
            f"Оплат: <b>{int(summary.get('payments_count') or 0)}</b>\n"
            f"Выручка: <b>{float(summary.get('revenue_rub') or 0):.2f} ₽</b>\n"
            f"Комиссия: <b>{float(summary.get('commission_rub') or 0):.2f} ₽</b>\n"
            f"Баланс к выплате: <b>{float(summary.get('balance_rub') or 0):.2f} ₽</b>\n"
            f"Сегодня: <b>{int(summary.get('today_payments') or 0)}</b> оплат, "
            f"<b>{float(summary.get('today_revenue_rub') or 0):.2f} ₽</b>\n"
            f"Уровень: <code>{html.escape(str(summary.get('tier') or 'basic'))}</code>, "
            f"{int(summary.get('percent') or 0)}%\n"
            f"Промокод: <code>{html.escape(referral_code or '-')}</code>"
        )
        if referral_link:
            lines.append(f"Ссылка: <code>{html.escape(referral_link)}</code>")
    return "\n".join(lines)


def _format_payouts(payouts: list[PartnerPayout]) -> str:
    if not payouts:
        return (
            "<b>Партнёрские выплаты</b>\n\n"
            "Заявок пока нет. Модель поддерживает статусы: ожидает, выплачено, заморожено."
        )
    status_titles = {
        "pending": "ожидает",
        "paid": "выплачено",
        "frozen": "заморожено",
    }
    lines = ["<b>Партнёрские выплаты</b>"]
    for payout in payouts[:10]:
        lines.append(
            f"\n#{payout.id} · <b>{payout.partner}</b>\n"
            f"Сумма: {payout.amount_rub:.2f} ₽\n"
            f"Статус: {status_titles.get(payout.status, payout.status)}\n"
            f"Комментарий: {payout.comment or '-'}"
        )
    return "\n".join(lines)


@router.message(Command("admin_referrals"))
async def cmd_admin_referrals(message: types.Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("Доступ запрещён")
        return
    await state.clear()
    config_data = await _service().get_config()
    await message.answer(
        _format_config(config_data),
        reply_markup=_settings_keyboard(config_data),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_ref:menu")
async def admin_referral_menu(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    await state.clear()
    config_data = await _service().get_config()
    await callback.message.edit_text(
        _format_config(config_data),
        reply_markup=_settings_keyboard(config_data),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_ref:set_referrer_bonus")
async def admin_referrer_bonus_prompt(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    await state.set_state(ReferralAdminStates.waiting_referrer_bonus)
    await callback.message.edit_text(
        "Введите бонус пригласившему в BoomCoin:",
        reply_markup=_back_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_ref:set_friend_bonus")
async def admin_friend_bonus_prompt(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    await state.set_state(ReferralAdminStates.waiting_friend_bonus)
    await callback.message.edit_text(
        "Введите бонус другу в BoomCoin:",
        reply_markup=_back_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_ref:set_daily_limit")
async def admin_daily_limit_prompt(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    await state.set_state(ReferralAdminStates.waiting_daily_limit)
    await callback.message.edit_text(
        "Введите дневной лимит рефералов:",
        reply_markup=_back_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_ref:trigger:"))
async def admin_referral_trigger(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    trigger = callback.data.rsplit(":", 1)[-1]
    config_data = await _service().update_config(bonus_trigger=trigger)
    await callback.message.edit_text(
        _format_config(config_data),
        reply_markup=_settings_keyboard(config_data),
        parse_mode="HTML",
    )
    await callback.answer("Настройка обновлена")


@router.callback_query(F.data == "admin_ref:antifraud")
async def admin_antifraud(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    config_data = await _service().get_config()
    await callback.message.edit_text(
        _format_antifraud(config_data),
        reply_markup=_antifraud_keyboard(config_data),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_ref:rule:"))
async def admin_toggle_antifraud_rule(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    rule_key = callback.data.rsplit(":", 1)[-1]
    config_data = await _service().get_config()
    rule = next((item for item in config_data.antifraud_rules if item.key == rule_key), None)
    if rule is None:
        await callback.answer("Правило не найдено", show_alert=True)
        return
    config_data = await _service().set_antifraud_rule_enabled(rule_key, not rule.enabled)
    await callback.message.edit_text(
        _format_antifraud(config_data),
        reply_markup=_antifraud_keyboard(config_data),
        parse_mode="HTML",
    )
    await callback.answer("Антифрод обновлён")


@router.callback_query(F.data == "admin_ref:partner_summary")
async def admin_partner_summary(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    summaries = await get_admin_partner_summaries(limit=10)
    bot_username = None
    try:
        me = await callback.bot.get_me()
        bot_username = me.username
    except Exception:
        bot_username = None
    await callback.message.edit_text(
        _format_partner_summaries(summaries, bot_username),
        reply_markup=_back_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_ref:payouts")
async def admin_partner_payouts(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    payouts = await _service().list_payouts()
    await callback.message.edit_text(
        _format_payouts(payouts),
        reply_markup=_back_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(StateFilter(ReferralAdminStates.waiting_referrer_bonus))
async def admin_save_referrer_bonus(message: types.Message, state: FSMContext) -> None:
    await _save_numeric_setting(
        message,
        state,
        field="referrer_bonus_credits",
        error_text="Введите целое число от 0.",
    )


@router.message(StateFilter(ReferralAdminStates.waiting_friend_bonus))
async def admin_save_friend_bonus(message: types.Message, state: FSMContext) -> None:
    await _save_numeric_setting(
        message,
        state,
        field="friend_bonus_credits",
        error_text="Введите целое число от 0.",
    )


@router.message(StateFilter(ReferralAdminStates.waiting_daily_limit))
async def admin_save_daily_limit(message: types.Message, state: FSMContext) -> None:
    await _save_numeric_setting(
        message,
        state,
        field="daily_referral_limit",
        error_text="Введите целое число от 0.",
    )


async def _save_numeric_setting(
    message: types.Message,
    state: FSMContext,
    *,
    field: str,
    error_text: str,
) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("Доступ запрещён")
        return
    try:
        value = int((message.text or "").strip())
    except ValueError:
        await message.answer(error_text)
        return
    if value < 0:
        await message.answer(error_text)
        return
    config_data = await _service().update_config(**{field: value})
    await state.clear()
    await message.answer(
        _format_config(config_data),
        reply_markup=_settings_keyboard(config_data),
        parse_mode="HTML",
    )
