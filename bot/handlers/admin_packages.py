from __future__ import annotations

import html
from typing import Any

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.config import config
from bot.services.admin_config_service import (
    AdminPackageConfigService,
    admin_package_config_service,
)
from bot.keyboards import get_credit_emoji, get_credit_plural


router = Router()


class AdminPackageStates(StatesGroup):
    waiting_price = State()
    waiting_bonus = State()
    waiting_discount = State()


def _is_admin(user_id: int) -> bool:
    return config.is_admin(user_id)


def format_package_line(package: dict[str, Any]) -> str:
    credit_emoji = get_credit_emoji()
    markers = []
    if package.get("popular"):
        markers.append("популярный")
    if package.get("hidden"):
        markers.append("скрыт")
    if package.get("discount_enabled"):
        markers.append(f"скидка {package.get('discount_percent', 0)}%")

    marker_text = f" ({', '.join(markers)})" if markers else ""
    bonus = int(package.get("bonus_credits", 0))
    bonus_text = f" + {bonus} бонус" if bonus else ""
    return (
        f"• <b>{html.escape(str(package.get('name', package.get('id'))))}</b>"
        f" <code>{html.escape(str(package.get('id')))}</code>{marker_text}\n"
        f"  {int(package.get('credits', 0))} {credit_emoji}{bonus_text} — "
        f"<b>{int(package.get('price_rub', 0))}</b> ₽"
    )


def format_packages_text(packages: list[dict[str, Any]]) -> str:
    credit_plural = get_credit_plural()
    if not packages:
        return f"📦 <b>Пакеты {html.escape(credit_plural)}</b>\n\nПакеты не найдены."
    lines = "\n\n".join(format_package_line(package) for package in packages)
    return f"📦 <b>Пакеты {html.escape(credit_plural)}</b>\n\n{lines}"


def get_admin_packages_keyboard(
    packages: list[dict[str, Any]],
) -> types.InlineKeyboardMarkup:
    rows: list[list[types.InlineKeyboardButton]] = []
    for package in packages:
        package_id = str(package.get("id"))
        hidden_text = "👁 Показать" if package.get("hidden") else "🙈 Скрыть"
        popular_text = "★ Популярный" if package.get("popular") else "☆ Популярным"
        discount_text = (
            "🏷 Изм. скидку" if package.get("discount_enabled") else "🏷 Скидка"
        )
        rows.append(
            [
                types.InlineKeyboardButton(
                    text=str(package.get("name", package_id)),
                    callback_data=f"admin_pkg_open:{package_id}",
                )
            ]
        )
        rows.append(
            [
                types.InlineKeyboardButton(
                    text="₽ Цена", callback_data=f"admin_pkg_price:{package_id}"
                ),
                types.InlineKeyboardButton(
                    text="🪙 Бонус", callback_data=f"admin_pkg_bonus:{package_id}"
                ),
            ]
        )
        rows.append(
            [
                types.InlineKeyboardButton(
                    text=popular_text, callback_data=f"admin_pkg_popular:{package_id}"
                ),
                types.InlineKeyboardButton(
                    text=hidden_text, callback_data=f"admin_pkg_hidden:{package_id}"
                ),
                types.InlineKeyboardButton(
                    text=discount_text, callback_data=f"admin_pkg_discount:{package_id}"
                ),
            ]
        )

    rows.append(
        [types.InlineKeyboardButton(text="🔙 Админ-панель", callback_data="admin_back")]
    )
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _back_to_packages_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🔙 К пакетам", callback_data="admin_packages"
                )
            ]
        ]
    )


async def _render_packages(
    target: types.Message,
    service: AdminPackageConfigService = admin_package_config_service,
) -> None:
    packages = await service.list_packages(include_hidden=True)
    await target.edit_text(
        format_packages_text(packages),
        reply_markup=get_admin_packages_keyboard(packages),
        parse_mode="HTML",
    )


@router.message(Command("admin_packages"))
async def cmd_admin_packages(message: types.Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    packages = await admin_package_config_service.list_packages(include_hidden=True)
    await message.answer(
        format_packages_text(packages),
        reply_markup=get_admin_packages_keyboard(packages),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_packages")
async def admin_packages(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    await state.clear()
    await _render_packages(callback.message)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_pkg_open:"))
async def admin_package_open(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    await _render_packages(callback.message)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_pkg_price:"))
async def admin_package_price_prompt(
    callback: types.CallbackQuery, state: FSMContext
) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    package_id = callback.data.split(":", 1)[1]
    package = await admin_package_config_service.get_package(package_id)
    if package is None:
        await callback.answer("Пакет не найден", show_alert=True)
        return
    await state.update_data(admin_package_id=package_id)
    await state.set_state(AdminPackageStates.waiting_price)
    await callback.message.edit_text(
        f"₽ <b>Цена пакета {html.escape(package['name'])}</b>\n\n"
        f"Текущая цена: <code>{package['price_rub']}</code> ₽\n"
        "Введите новую цену целым числом:",
        reply_markup=_back_to_packages_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_pkg_bonus:"))
async def admin_package_bonus_prompt(
    callback: types.CallbackQuery, state: FSMContext
) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    package_id = callback.data.split(":", 1)[1]
    package = await admin_package_config_service.get_package(package_id)
    if package is None:
        await callback.answer("Пакет не найден", show_alert=True)
        return
    await state.update_data(admin_package_id=package_id)
    await state.set_state(AdminPackageStates.waiting_bonus)
    await callback.message.edit_text(
        f"🪙 <b>Бонус пакета {html.escape(package['name'])}</b>\n\n"
        f"Текущий бонус: <code>{package['bonus_credits']}</code> 🪙\n"
        "Введите новый бонус целым числом:",
        reply_markup=_back_to_packages_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_pkg_discount:"))
async def admin_package_discount_prompt(
    callback: types.CallbackQuery, state: FSMContext
) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    package_id = callback.data.split(":", 1)[1]
    package = await admin_package_config_service.get_package(package_id)
    if package is None:
        await callback.answer("Пакет не найден", show_alert=True)
        return
    await state.update_data(admin_package_id=package_id)
    await state.set_state(AdminPackageStates.waiting_discount)
    await callback.message.edit_text(
        f"🏷 <b>Скидка пакета {html.escape(package['name'])}</b>\n\n"
        f"Текущая скидка: <code>{package.get('discount_percent', 0)}</code>%\n"
        "Введите процент скидки от 1 до 95 или 0, чтобы выключить:",
        reply_markup=_back_to_packages_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_pkg_popular:"))
async def admin_package_set_popular(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    package_id = callback.data.split(":", 1)[1]
    result = await admin_package_config_service.set_popular(package_id)
    if not result.ok:
        await callback.answer("Пакет не найден", show_alert=True)
        return
    await _render_packages(callback.message)
    await callback.answer("Пакет отмечен популярным")


@router.callback_query(F.data.startswith("admin_pkg_hidden:"))
async def admin_package_toggle_hidden(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    package_id = callback.data.split(":", 1)[1]
    package = await admin_package_config_service.get_package(package_id)
    if package is None:
        await callback.answer("Пакет не найден", show_alert=True)
        return
    result = await admin_package_config_service.set_hidden(
        package_id, not bool(package.get("hidden"))
    )
    if not result.ok:
        await callback.answer("Пакет не найден", show_alert=True)
        return
    await _render_packages(callback.message)
    await callback.answer("Видимость обновлена")


@router.message(AdminPackageStates.waiting_price)
async def admin_package_set_price(message: types.Message, state: FSMContext) -> None:
    data = await state.get_data()
    package_id = str(data.get("admin_package_id", ""))
    try:
        price = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Введите цену целым числом.")
        return

    result = await admin_package_config_service.set_price(package_id, price)
    if not result.ok:
        await message.answer("❌ Не удалось обновить цену.")
        return
    await state.clear()
    packages = await admin_package_config_service.list_packages(include_hidden=True)
    await message.answer(
        "✅ Цена обновлена.\n\n" + format_packages_text(packages),
        reply_markup=get_admin_packages_keyboard(packages),
        parse_mode="HTML",
    )


@router.message(AdminPackageStates.waiting_bonus)
async def admin_package_set_bonus(message: types.Message, state: FSMContext) -> None:
    data = await state.get_data()
    package_id = str(data.get("admin_package_id", ""))
    try:
        bonus = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Введите бонус целым числом.")
        return

    result = await admin_package_config_service.set_bonus(package_id, bonus)
    if not result.ok:
        await message.answer("❌ Не удалось обновить бонус.")
        return
    await state.clear()
    packages = await admin_package_config_service.list_packages(include_hidden=True)
    await message.answer(
        "✅ Бонус обновлен.\n\n" + format_packages_text(packages),
        reply_markup=get_admin_packages_keyboard(packages),
        parse_mode="HTML",
    )


@router.message(AdminPackageStates.waiting_discount)
async def admin_package_set_discount(message: types.Message, state: FSMContext) -> None:
    data = await state.get_data()
    package_id = str(data.get("admin_package_id", ""))
    try:
        discount = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Введите скидку целым числом.")
        return

    result = await admin_package_config_service.set_discount(package_id, discount)
    if not result.ok:
        await message.answer("❌ Скидка должна быть от 0 до 95%.")
        return
    await state.clear()
    packages = await admin_package_config_service.list_packages(include_hidden=True)
    await message.answer(
        "✅ Скидка обновлена.\n\n" + format_packages_text(packages),
        reply_markup=get_admin_packages_keyboard(packages),
        parse_mode="HTML",
    )
