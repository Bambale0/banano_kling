import json
import logging
from pathlib import Path

from aiogram import Bot, F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.database import add_credits, deduct_credits, get_admin_stats, get_user_stats
from bot.keyboards import (
    get_admin_keyboard,
    get_admin_price_image_keyboard,
    get_admin_price_video_keyboard,
    get_admin_prices_keyboard,
    get_back_keyboard,
)
from bot.services.preset_manager import preset_manager
from bot.states import AdminStates

PRICE_PATH = Path("data/price.json")

logger = logging.getLogger(__name__)
router = Router()


def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором"""
    return config.is_admin(user_id)


@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    """Открывает админ-панель"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к админ-панели.")
        return

    stats = await get_admin_stats()

    text = f"""
🔧 <b>Админ-панель</b>

📊 <b>Статистика:</b>
• Пользователей: <code>{stats['total_users']}</code>
• Генераций: <code>{stats['total_generations']}</code>
• Транзакций: <code>{stats['total_transactions']}</code>
• Выручка: <code>{stats['total_revenue']:.0f}</code> ₽

Выберите действие:
"""

    await message.answer(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "admin_reload")
async def admin_reload_presets(callback: types.CallbackQuery):
    """Перезагружает пресеты из JSON"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    # Пресеты теперь не используются
    await callback.answer(
        "✅ Пресеты отключены в этой версии",
        show_alert=True,
    )


@router.callback_query(F.data == "admin_stats")
async def admin_show_stats(callback: types.CallbackQuery):
    """Показывает детальную статистику"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    stats = await get_admin_stats()

    text = f"""
📊 <b>Детальная статистика</b>

👥 <b>Пользователи:</b>
• Всего: <code>{stats['total_users']}</code>

🎨 <b>Генерации:</b>
• Всего: <code>{stats['total_generations']}</code>

💳 <b>Платежи:</b>
• Транзакций: <code>{stats['total_transactions']}</code>
• Выручка: <code>{stats['total_revenue']:.0f}</code> ₽
"""

    await callback.message.edit_text(
        text, reply_markup=get_back_keyboard("admin_back"), parse_mode="HTML"
    )


@router.callback_query(F.data == "admin_users")
async def admin_users_menu(callback: types.CallbackQuery, state: FSMContext):
    """Меню управления пользователями"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await callback.message.edit_text(
        "👥 <b>Управление пользователями</b>" "Введите Telegram ID пользователя:",
        reply_markup=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_user_id)


@router.message(AdminStates.waiting_user_id)
async def admin_process_user_id(message: types.Message, state: FSMContext):
    """Обрабатывает ввод ID пользователя"""
    try:
        user_id = int(message.text)
    except ValueError:
        await message.answer("❌ Неверный формат ID. Введите число:")
        return

    # Получаем статистику пользователя
    try:
        stats = await get_user_stats(user_id)
    except Exception as e:
        logger.warning(f"User {user_id} not found: {e}")
        await message.answer(f"❌ Пользователь с ID {user_id} не найден.")
        return

    await state.update_data(target_user_id=user_id)

    text = f"""
👤 <b>Пользователь</b>

🆔 ID: <code>{user_id}</code>
💰 Кредитов: <code>{stats['credits']}</code>
📊 Генераций: <code>{stats['generations']}</code>
💸 Потрачено: <code>{stats['total_spent']}</code>
📅 Регистрация: <code>{stats['member_since']}</code>

Выберите действие:
"""

    await message.answer(
        text,
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="➕ Добавить кредиты",
                        callback_data=f"admin_add_credits_{user_id}",
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="➖ Списать кредиты",
                        callback_data=f"admin_deduct_credits_{user_id}",
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="🔙 Назад", callback_data="admin_back"
                    )
                ],
            ]
        ),
        parse_mode="HTML",
    )

    await state.clear()


@router.callback_query(F.data.startswith("admin_add_credits_"))
async def admin_add_credits_prompt(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает количество кредитов для добавления"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    user_id = int(callback.data.replace("admin_add_credits_", ""))
    await state.update_data(target_user_id=user_id, action="add")

    await callback.message.edit_text(
        f"➕ <b>Добавление кредитов</b>"
        f"Пользователь ID: <code>{user_id}</code>"
        f"Введите количество кредитов для добавления:",
        reply_markup=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_credits_amount)


@router.callback_query(F.data.startswith("admin_deduct_credits_"))
async def admin_deduct_credits_prompt(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает количество кредитов для списания"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    user_id = int(callback.data.replace("admin_deduct_credits_", ""))
    await state.update_data(target_user_id=user_id, action="deduct")

    await callback.message.edit_text(
        f"➖ <b>Списание кредитов</b>"
        f"Пользователь ID: <code>{user_id}</code>"
        f"Введите количество кредитов для списания:",
        reply_markup=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_credits_amount)


@router.message(AdminStates.waiting_credits_amount)
async def admin_process_credits_amount(message: types.Message, state: FSMContext):
    """Обрабатывает ввод количества кредитов"""
    try:
        amount = int(message.text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Неверное количество. Введите положительное число:")
        return

    data = await state.get_data()
    user_id = data.get("target_user_id")
    action = data.get("action")

    if action == "add":
        success = await add_credits(user_id, amount, reason="admin_adjustment_add", external_id=f"admin:{message.from_user.id}:add:{user_id}:{message.message_id}")
        action_text = f"добавлено <code>{amount}</code> кредитов"
    else:
        # Для списания нужно реализовать deduct_credits_by_admin
        from bot.database import deduct_credits

        success = await deduct_credits(user_id, amount, reason="admin_adjustment_deduct", external_id=f"admin:{message.from_user.id}:deduct:{user_id}:{message.message_id}")
        action_text = f"списано <code>{amount}</code> кредитов"

    if success:
        stats = await get_user_stats(user_id)
        await message.answer(
            f"✅ <b>Успешно!</b>"
            f"Пользователь ID: <code>{user_id}</code>\n"
            f"Действие: {action_text}\n"
            f"Текущий баланс: <code>{stats['credits']}</code> кредитов",
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            f"❌ Ошибка! Возможно, недостаточно кредитов для списания.",
            reply_markup=get_admin_keyboard(),
        )

    await state.clear()


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_prompt(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает текст рассылки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await callback.message.edit_text(
        "📢 <b>Рассылка всем пользователям</b>"
        "Введите текст сообщения для рассылки:\n"
        "<i>Поддерживается HTML-форматирование</i>",
        reply_markup=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_broadcast_text)


@router.message(AdminStates.waiting_broadcast_text)
async def admin_process_broadcast_text(message: types.Message, state: FSMContext):
    """Сохраняет текст и предлагает прикрепить фото"""
    await state.update_data(broadcast_text=message.text, broadcast_photo_id=None)

    await message.answer(
        "🖼 <b>Хотите прикрепить изображение к рассылке?</b>\n\n"
        "Отправьте фото или нажмите «Пропустить».",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="⏭ Пропустить", callback_data="admin_broadcast_skip_photo"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="❌ Отмена", callback_data="admin_back"
                    ),
                ],
            ]
        ),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_broadcast_photo)


@router.message(AdminStates.waiting_broadcast_photo, F.photo)
async def admin_broadcast_photo_received(message: types.Message, state: FSMContext):
    """Получает фото и показывает превью"""
    photo_file_id = message.photo[-1].file_id
    await state.update_data(broadcast_photo_id=photo_file_id)
    await _show_broadcast_preview(message, state)


@router.callback_query(F.data == "admin_broadcast_skip_photo")
async def admin_broadcast_skip_photo(callback: types.CallbackQuery, state: FSMContext):
    """Пропускает фото и показывает превью"""
    await state.update_data(broadcast_photo_id=None)
    await callback.message.delete()
    await _show_broadcast_preview(callback.message, state, from_callback=True)


async def _show_broadcast_preview(
    message: types.Message,
    state: FSMContext,
    from_callback: bool = False,
) -> None:
    """Показывает превью рассылки"""
    data = await state.get_data()
    broadcast_text = data.get("broadcast_text", "")
    photo_id = data.get("broadcast_photo_id")

    confirm_kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="✅ Отправить", callback_data="admin_broadcast_confirm"
                ),
                types.InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back"),
            ]
        ]
    )

    photo_hint = "🖼 <i>С изображением</i>" if photo_id else "📝 <i>Только текст</i>"
    preview_text = (
        f"📢 <b>Превью рассылки:</b> {photo_hint}\n"
        "───────────────\n"
        f"{broadcast_text}\n"
        "───────────────\n"
        "Подтверждаете отправку?"
    )

    if photo_id:
        await message.answer_photo(
            photo=photo_id,
            caption=preview_text,
            reply_markup=confirm_kb,
            parse_mode="HTML",
        )
    else:
        await message.answer(
            preview_text,
            reply_markup=confirm_kb,
            parse_mode="HTML",
        )

    await state.set_state(AdminStates.confirming_broadcast)


@router.callback_query(F.data == "admin_broadcast_confirm")
async def admin_execute_broadcast(
    callback: types.CallbackQuery, state: FSMContext, bot: Bot
):
    """Выполняет рассылку"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    data = await state.get_data()
    broadcast_text = data.get("broadcast_text")
    broadcast_photo_id = data.get("broadcast_photo_id")

    # Если превью было с фото — редактируем caption, иначе текст
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                "📢 <b>Рассылка запущена...</b>", parse_mode="HTML"
            )
        else:
            await callback.message.edit_text(
                "📢 <b>Рассылка запущена...</b>", parse_mode="HTML"
            )
    except Exception:
        await callback.message.answer(
            "📢 <b>Рассылка запущена...</b>", parse_mode="HTML"
        )

    # Получаем всех пользователей
    import aiosqlite

    from bot.database import DATABASE_PATH

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT telegram_id FROM users")
        users = await cursor.fetchall()

    success_count = 0
    error_count = 0

    for user in users:
        try:
            if broadcast_photo_id:
                await bot.send_photo(
                    user["telegram_id"],
                    photo=broadcast_photo_id,
                    caption=broadcast_text,
                    parse_mode="HTML",
                )
            else:
                await bot.send_message(
                    user["telegram_id"], broadcast_text, parse_mode="HTML"
                )
            success_count += 1
        except Exception as e:
            logger.warning(f"Broadcast failed for {user['telegram_id']}: {e}")
            error_count += 1

    result_text = (
        f"📢 <b>Рассылка завершена!</b>\n"
        f"✅ Успешно: <code>{success_count}</code>\n"
        f"❌ Ошибок: <code>{error_count}</code>"
    )
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                result_text,
                reply_markup=get_admin_keyboard(),
                parse_mode="HTML",
            )
        else:
            await callback.message.edit_text(
                result_text,
                reply_markup=get_admin_keyboard(),
                parse_mode="HTML",
            )
    except Exception:
        await callback.message.answer(
            result_text,
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML",
        )

    await state.clear()


@router.callback_query(F.data == "admin_back")
async def admin_back_to_menu(callback: types.CallbackQuery):
    """Возврат в админ-меню"""
    stats = await get_admin_stats()

    text = f"""
🔧 <b>Админ-панель</b>

📊 <b>Статистика:</b>
• Пользователей: <code>{stats['total_users']}</code>
• Генераций: <code>{stats['total_generations']}</code>
• Транзакций: <code>{stats['total_transactions']}</code>
• Выручка: <code>{stats['total_revenue']:.0f}</code> ₽

Выберите действие:
"""

    await callback.message.edit_text(
        text, reply_markup=get_admin_keyboard(), parse_mode="HTML"
    )


# ---------------------------------------------------------------------------
# Price editing
# ---------------------------------------------------------------------------


def _load_price_json() -> dict:
    with open(PRICE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_price_json(data: dict):
    with open(PRICE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    preset_manager.reload()


@router.callback_query(F.data == "admin_prices")
async def admin_prices_menu(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    await callback.message.edit_text(
        "💰 <b>Управление ценами</b>\n\nВыберите категорию:",
        reply_markup=get_admin_prices_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_price_cat_image")
async def admin_price_cat_image(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    price_config = _load_price_json()
    await callback.message.edit_text(
        "🖼 <b>Цены на изображения</b>\n\nНажмите на модель для изменения цены:",
        reply_markup=get_admin_price_image_keyboard(price_config),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_price_cat_video")
async def admin_price_cat_video(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    price_config = _load_price_json()
    await callback.message.edit_text(
        "🎬 <b>Цены на видео</b>\n\nНажмите на модель для изменения цены:",
        reply_markup=get_admin_price_video_keyboard(price_config),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_price_img_"))
async def admin_price_img_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    key = callback.data.removeprefix("admin_price_img_")
    price_config = _load_price_json()
    current = (
        price_config.get("costs_reference", {}).get("image_models", {}).get(key, "?")
    )
    await state.update_data(price_type="image", price_key=key)
    await state.set_state(AdminStates.waiting_price_value)
    await callback.message.edit_text(
        f"🖼 <b>Изменение цены: <code>{key}</code></b>\n\n"
        f"Текущая цена: <code>{current}</code> 🍌\n\n"
        f"Введите новую цену (целое число):",
        reply_markup=get_back_keyboard("admin_price_cat_image"),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_price_vid_"))
async def admin_price_vid_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    key = callback.data.removeprefix("admin_price_vid_")
    price_config = _load_price_json()
    model_data = (
        price_config.get("costs_reference", {}).get("video_models", {}).get(key, {})
    )

    if "fixed_cost" in model_data:
        hint = (
            f"Текущая цена: <code>{model_data['fixed_cost']}</code> 🍌 (фиксированная)\n\n"
            f"Введите новую цену (целое число):"
        )
        await state.update_data(price_type="video_fixed", price_key=key)
    else:
        dur = model_data.get("duration_costs", {})
        dur_str = ", ".join(f"{d}с:{c}" for d, c in dur.items())
        hint = (
            f"Текущий базовый тариф: <code>{model_data.get('base', '?')}</code> 🍌\n"
            f"Цены по длительности: <code>{dur_str}</code>\n\n"
            f"Введите цены в формате <code>5:15,10:30,15:45</code>\n"
            f"(длительность_сек:цена через запятую)"
        )
        await state.update_data(price_type="video_duration", price_key=key)

    await state.set_state(AdminStates.waiting_price_value)
    await callback.message.edit_text(
        f"🎬 <b>Изменение цены: <code>{key}</code></b>\n\n{hint}",
        reply_markup=get_back_keyboard("admin_price_cat_video"),
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_price_value)
async def admin_process_price_value(message: types.Message, state: FSMContext):
    data = await state.get_data()
    price_type = data.get("price_type")
    price_key = data.get("price_key")
    text = message.text.strip()

    try:
        price_config = _load_price_json()
        costs = price_config.setdefault("costs_reference", {})

        if price_type == "image":
            new_price = int(text)
            costs.setdefault("image_models", {})[price_key] = new_price
            _save_price_json(price_config)
            await state.clear()
            await message.answer(
                f"✅ Цена для <code>{price_key}</code> обновлена: <b>{new_price}</b> 🍌",
                reply_markup=get_admin_keyboard(),
                parse_mode="HTML",
            )

        elif price_type == "video_fixed":
            new_price = int(text)
            model_data = costs.setdefault("video_models", {}).setdefault(price_key, {})
            model_data["fixed_cost"] = new_price
            model_data["base"] = new_price
            _save_price_json(price_config)
            await state.clear()
            await message.answer(
                f"✅ Цена для <code>{price_key}</code> обновлена: <b>{new_price}</b> 🍌",
                reply_markup=get_admin_keyboard(),
                parse_mode="HTML",
            )

        elif price_type == "video_duration":
            # parse "5:15,10:30,15:45"
            pairs = {}
            for part in text.split(","):
                part = part.strip()
                if ":" not in part:
                    raise ValueError(f"Bad format: {part}")
                dur, cost = part.split(":", 1)
                pairs[dur.strip()] = int(cost.strip())
            if not pairs:
                raise ValueError("Empty duration list")
            model_data = costs.setdefault("video_models", {}).setdefault(price_key, {})
            model_data["duration_costs"] = pairs
            model_data["base"] = min(pairs.values())
            _save_price_json(price_config)
            dur_str = ", ".join(f"{d}с: {c}🍌" for d, c in pairs.items())
            await state.clear()
            await message.answer(
                f"✅ Цены для <code>{price_key}</code> обновлены:\n{dur_str}",
                reply_markup=get_admin_keyboard(),
                parse_mode="HTML",
            )
        else:
            await state.clear()
            await message.answer(
                "❌ Неизвестный тип цены.", reply_markup=get_admin_keyboard()
            )

    except ValueError as e:
        await message.answer(
            f"❌ Неверный формат: <code>{e}</code>\n\nПопробуйте ещё раз:",
            parse_mode="HTML",
        )
