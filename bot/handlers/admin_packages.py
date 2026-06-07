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
    waiting_credits = State()
    waiting_bonus = State()
    waiting_days = State()
    waiting_image_limit = State()
    waiting_video_limit = State()
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
    is_subscription = int(package.get("subscription_days") or 0) > 0
    type_text = "подписка" if is_subscription else "кредиты"
    limit_text = ""
    if is_subscription:
        video_limit = int(package.get("video_limit") or 0)
        video_text = f", видео {video_limit}" if video_limit else ", без видео"
        pro_text = ", Banana Pro" if package.get("includes_pro") else ""
        priority_text = ", приоритет" if package.get("priority") else ""
        limit_text = (
            f"\n  🧾 {int(package.get('subscription_days', 0))} дн., "
            f"фото {int(package.get('image_limit', 0))}{video_text}{pro_text}{priority_text}"
        )
    return (
        f"• <b>{html.escape(str(package.get('name', package.get('id'))))}</b>"
        f" <code>{html.escape(str(package.get('id')))}</code> · {type_text}{marker_text}\n"
        f"  {int(package.get('credits', 0))} {credit_emoji}{bonus_text} — "
        f"<b>{int(package.get('price_rub', 0))}</b> ₽"
        f"{limit_text}"
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
                    text="🪙 Кредиты", callback_data=f"admin_pkg_credits:{package_id}"
                ),
                types.InlineKeyboardButton(
                    text="🪙 Бонус", callback_data=f"admin_pkg_bonus:{package_id}"
                ),
            ]
        )
        if int(package.get("subscription_days") or 0) > 0:
            pro_text = "✅ Pro" if package.get("includes_pro") else "Pro выкл."
            priority_text = (
                "✅ Приоритет" if package.get("priority") else "Приоритет выкл."
            )
            rows.append(
                [
                    types.InlineKeyboardButton(
                        text="⏳ Дни", callback_data=f"admin_pkg_days:{package_id}"
                    ),
                    types.InlineKeyboardButton(
                        text="🖼 Фото", callback_data=f"admin_pkg_images:{package_id}"
                    ),
                    types.InlineKeyboardButton(
                        text="🎬 Видео", callback_data=f"admin_pkg_videos:{package_id}"
                    ),
                ]
            )
            rows.append(
                [
                    types.InlineKeyboardButton(
                        text=pro_text, callback_data=f"admin_pkg_pro:{package_id}"
                    ),
                    types.InlineKeyboardButton(
                        text=priority_text,
                        callback_data=f"admin_pkg_priority:{package_id}",
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


@router.callback_query(F.data.startswith("admin_pkg_credits:"))
async def admin_package_credits_prompt(
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
    await state.set_state(AdminPackageStates.waiting_credits)
    await callback.message.edit_text(
        f"🪙 <b>Кредиты пакета {html.escape(package['name'])}</b>\n\n"
        f"Текущее количество: <code>{package['credits']}</code> 🪙\n"
        "Введите новое количество целым числом:",
        reply_markup=_back_to_packages_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


async def _subscription_limit_prompt(
    callback: types.CallbackQuery,
    state: FSMContext,
    *,
    field: str,
    title: str,
    current_label: str,
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
    await state.set_state(getattr(AdminPackageStates, field))
    await callback.message.edit_text(
        f"{title} <b>{html.escape(package['name'])}</b>\n\n"
        f"Текущее значение: <code>{current_label}</code>\n"
        "Введите новое значение целым числом:",
        reply_markup=_back_to_packages_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_pkg_days:"))
async def admin_package_days_prompt(
    callback: types.CallbackQuery, state: FSMContext
) -> None:
    package_id = callback.data.split(":", 1)[1]
    package = await admin_package_config_service.get_package(package_id)
    current = package.get("subscription_days", 0) if package else 0
    await _subscription_limit_prompt(
        callback,
        state,
        field="waiting_days",
        title="⏳ <b>Срок подписки</b>",
        current_label=f"{current} дней",
    )


@router.callback_query(F.data.startswith("admin_pkg_images:"))
async def admin_package_images_prompt(
    callback: types.CallbackQuery, state: FSMContext
) -> None:
    package_id = callback.data.split(":", 1)[1]
    package = await admin_package_config_service.get_package(package_id)
    current = package.get("image_limit", 0) if package else 0
    await _subscription_limit_prompt(
        callback,
        state,
        field="waiting_image_limit",
        title="🖼 <b>Фото-лимит</b>",
        current_label=f"{current} фото",
    )


@router.callback_query(F.data.startswith("admin_pkg_videos:"))
async def admin_package_videos_prompt(
    callback: types.CallbackQuery, state: FSMContext
) -> None:
    package_id = callback.data.split(":", 1)[1]
    package = await admin_package_config_service.get_package(package_id)
    current = package.get("video_limit", 0) if package else 0
    await _subscription_limit_prompt(
        callback,
        state,
        field="waiting_video_limit",
        title="🎬 <b>Видео-лимит</b>",
        current_label=f"{current} видео",
    )


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


@router.callback_query(F.data.startswith("admin_pkg_pro:"))
async def admin_package_toggle_pro(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    package_id = callback.data.split(":", 1)[1]
    package = await admin_package_config_service.get_package(package_id)
    if package is None:
        await callback.answer("Пакет не найден", show_alert=True)
        return
    result = await admin_package_config_service.set_bool_field(
        package_id, "includes_pro", not bool(package.get("includes_pro"))
    )
    if not result.ok:
        await callback.answer("Не удалось обновить Banana Pro", show_alert=True)
        return
    await _render_packages(callback.message)
    await callback.answer("Banana Pro обновлен")


@router.callback_query(F.data.startswith("admin_pkg_priority:"))
async def admin_package_toggle_priority(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    package_id = callback.data.split(":", 1)[1]
    package = await admin_package_config_service.get_package(package_id)
    if package is None:
        await callback.answer("Пакет не найден", show_alert=True)
        return
    result = await admin_package_config_service.set_bool_field(
        package_id, "priority", not bool(package.get("priority"))
    )
    if not result.ok:
        await callback.answer("Не удалось обновить приоритет", show_alert=True)
        return
    await _render_packages(callback.message)
    await callback.answer("Приоритет обновлен")


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


@router.message(AdminPackageStates.waiting_credits)
async def admin_package_set_credits(message: types.Message, state: FSMContext) -> None:
    data = await state.get_data()
    package_id = str(data.get("admin_package_id", ""))
    try:
        credits = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Введите количество целым числом.")
        return

    result = await admin_package_config_service.set_credits(package_id, credits)
    if not result.ok:
        await message.answer("❌ Количество не может быть отрицательным.")
        return
    await state.clear()
    packages = await admin_package_config_service.list_packages(include_hidden=True)
    await message.answer(
        "✅ Кредиты обновлены.\n\n" + format_packages_text(packages),
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


async def _set_subscription_number(
    message: types.Message,
    state: FSMContext,
    *,
    setter_name: str,
    success_text: str,
    error_text: str,
) -> None:
    data = await state.get_data()
    package_id = str(data.get("admin_package_id", ""))
    try:
        value = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Введите значение целым числом.")
        return

    setter = getattr(admin_package_config_service, setter_name)
    result = await setter(package_id, value)
    if not result.ok:
        await message.answer(error_text)
        return
    await state.clear()
    packages = await admin_package_config_service.list_packages(include_hidden=True)
    await message.answer(
        f"✅ {success_text}\n\n" + format_packages_text(packages),
        reply_markup=get_admin_packages_keyboard(packages),
        parse_mode="HTML",
    )


@router.message(AdminPackageStates.waiting_days)
async def admin_package_set_days(message: types.Message, state: FSMContext) -> None:
    await _set_subscription_number(
        message,
        state,
        setter_name="set_subscription_days",
        success_text="Срок подписки обновлен.",
        error_text="❌ Срок не может быть отрицательным.",
    )


@router.message(AdminPackageStates.waiting_image_limit)
async def admin_package_set_images(message: types.Message, state: FSMContext) -> None:
    await _set_subscription_number(
        message,
        state,
        setter_name="set_image_limit",
        success_text="Фото-лимит обновлен.",
        error_text="❌ Фото-лимит не может быть отрицательным.",
    )


@router.message(AdminPackageStates.waiting_video_limit)
async def admin_package_set_videos(message: types.Message, state: FSMContext) -> None:
    await _set_subscription_number(
        message,
        state,
        setter_name="set_video_limit",
        success_text="Видео-лимит обновлен.",
        error_text="❌ Видео-лимит не может быть отрицательным.",
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
