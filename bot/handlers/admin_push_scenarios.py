from __future__ import annotations

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.services.push_scenario_service import push_scenario_service


router = Router()


def _is_admin(user_id: int) -> bool:
    return config.is_admin(user_id)


def _keyboard(enabled: bool) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Выключить" if enabled else "Включить",
        callback_data="push_scenarios:toggle",
    )
    builder.button(text="Preview due", callback_data="push_scenarios:preview")
    builder.adjust(1)
    return builder.as_markup()


async def _status_text() -> str:
    service_config = await push_scenario_service.get_config()
    lines = [
        "<b>Push-сценарии</b>",
        f"Статус: {'включены' if service_config.enabled else 'выключены'}",
        "",
        "Сценарии:",
    ]
    for rule in service_config.rules:
        hours = int(rule.delay.total_seconds() // 3600)
        delay = f"{hours} ч." if hours < 48 else f"{hours // 24} д."
        lines.append(
            f"- {rule.title}: {'on' if rule.enabled else 'off'}, delay {delay}"
        )
    lines.extend(
        [
            "",
            "Этот роутер только показывает настройки и due-события.",
            "Массовая отправка здесь не выполняется.",
        ]
    )
    return "\n".join(lines)


@router.message(Command("admin_push_scenarios"))
async def admin_push_scenarios(message: types.Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    service_config = await push_scenario_service.get_config()
    await message.answer(
        await _status_text(),
        reply_markup=_keyboard(service_config.enabled),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "push_scenarios:menu")
async def admin_push_scenarios_menu(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    service_config = await push_scenario_service.get_config()
    await callback.message.edit_text(
        await _status_text(),
        reply_markup=_keyboard(service_config.enabled),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "push_scenarios:toggle")
async def toggle_push_scenarios(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    service_config = await push_scenario_service.get_config()
    updated = await push_scenario_service.set_enabled(not service_config.enabled)
    await callback.message.edit_text(
        await _status_text(),
        reply_markup=_keyboard(updated.enabled),
        parse_mode="HTML",
    )
    await callback.answer("Готово")


@router.message(Command("admin_push_scenarios_preview"))
async def admin_push_scenarios_preview(message: types.Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    events = await push_scenario_service.collect_due_events(limit=20)
    await message.answer(_format_preview(events), parse_mode="HTML")


@router.callback_query(F.data == "push_scenarios:preview")
async def push_scenarios_preview(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    events = await push_scenario_service.collect_due_events(limit=20)
    await callback.message.edit_text(
        _format_preview(events),
        reply_markup=_keyboard((await push_scenario_service.get_config()).enabled),
        parse_mode="HTML",
    )
    await callback.answer()


def _format_preview(events: list) -> str:
    if not events:
        return "<b>Push due-события</b>\n\nСейчас нет событий к обработке."

    lines = ["<b>Push due-события</b>", ""]
    for event in events:
        lines.append(
            f"- {event.title}: user_id={event.user_id}, "
            f"telegram_id={event.telegram_id}, key={event.event_key}"
        )
    lines.extend(["", "Preview не отправляет сообщения пользователям."])
    return "\n".join(lines)
