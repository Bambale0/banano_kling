import logging
import os
import uuid

from aiogram import Bot, F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.database import (
    add_credits,
    add_shop_product_image,
    deduct_credits,
    get_admin_stats,
    get_recent_shop_orders,
    get_shop_product_images,
    get_user_stats,
    set_shop_product_primary_image,
    upsert_shop_product_override,
)
from bot.keyboards import get_admin_keyboard, get_back_keyboard
from bot.states import AdminStates

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


def get_admin_shop_keyboard(article: str | None = None):
    rows = []
    if article:
        rows.extend(
            [
                [
                    types.InlineKeyboardButton(
                        text="🖼 Добавить фото",
                        callback_data=f"admin_shop_photo:{article}",
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="⭐ Выбрать главное фото",
                        callback_data=f"admin_shop_primary:{article}",
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="📦 Изменить остаток",
                        callback_data=f"admin_shop_stock:{article}",
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="💰 Изменить цену",
                        callback_data=f"admin_shop_price:{article}",
                    )
                ],
            ]
        )
    rows.append(
        [
            types.InlineKeyboardButton(
                text="🔎 Другой артикул", callback_data="admin_shop"
            )
        ]
    )
    rows.append(
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    )
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "admin_shop")
async def admin_shop_menu(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await callback.message.edit_text(
        "🛍 <b>Управление магазином</b>\n\n"
        "Введите артикул WB товара, которому нужно обновить фото, остаток или цену:",
        reply_markup=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )
    await state.set_state(AdminStates.waiting_shop_article)


@router.message(AdminStates.waiting_shop_article)
async def admin_shop_article(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    article = (message.text or "").strip()
    if not article.isdigit():
        await message.answer("❌ Введите числовой артикул WB:")
        return

    await state.update_data(shop_article=article)
    await message.answer(
        f"🛍 <b>Товар WB</b>: <code>{article}</code>\n\n" "Что обновляем?",
        reply_markup=get_admin_shop_keyboard(article),
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data.startswith("admin_shop_photo:"))
async def admin_shop_photo_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    article = callback.data.split(":", 1)[1]
    await state.update_data(shop_article=article)
    await callback.message.edit_text(
        f"🖼 <b>Фото товара</b>\n\nWB: <code>{article}</code>\n\n"
        "Отправьте одно или несколько фото товара.\n"
        "Можно отправлять их по одному сообщению или альбомом.",
        reply_markup=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )
    await state.set_state(AdminStates.waiting_shop_photo)


@router.message(AdminStates.waiting_shop_photo, F.photo)
async def admin_shop_photo_save(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    article = data.get("shop_article")
    if not article:
        await message.answer("❌ Артикул не найден. Начните заново через /admin.")
        await state.clear()
        return

    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    image_bytes = await message.bot.download_file(file.file_path)
    os.makedirs("static/shop/products", exist_ok=True)
    filename = f"{article}_{uuid.uuid4().hex[:8]}.jpg"
    path = os.path.join("static", "shop", "products", filename)
    with open(path, "wb") as output:
        output.write(image_bytes.read())

    image_url = f"/shop/assets/products/{filename}"
    existing_images = await get_shop_product_images(article)
    is_primary = not bool(existing_images.get(article))
    image_id = await add_shop_product_image(
        article,
        image_url,
        is_primary=is_primary,
        created_by=message.from_user.id,
    )
    if is_primary:
        await upsert_shop_product_override(
            article, image_url=image_url, updated_by=message.from_user.id
        )
    await message.answer(
        f"✅ Фото #{image_id} сохранено для WB <code>{article}</code>.\n"
        f"{'Оно назначено главным.' if is_primary else 'Главное фото можно выбрать отдельной кнопкой.'}\n"
        "Можно отправить ещё фото или нажать «Назад».",
        reply_markup=get_admin_shop_keyboard(article),
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_shop_photo)
async def admin_shop_photo_invalid(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "❌ Отправьте фото товара. Если закончили, нажмите «Назад» в админ-меню."
    )


@router.callback_query(F.data.startswith("admin_shop_primary:"))
async def admin_shop_primary_menu(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    article = callback.data.split(":", 1)[1]
    images = (await get_shop_product_images(article)).get(article, [])
    if not images:
        await callback.message.edit_text(
            f"⭐ <b>Главное фото</b>\n\nWB: <code>{article}</code>\n\n"
            "Фото пока нет. Сначала загрузите фото товара.",
            reply_markup=get_admin_shop_keyboard(article),
            parse_mode="HTML",
        )
        return

    rows = []
    for index, image in enumerate(images, start=1):
        prefix = "✅ " if image["is_primary"] else ""
        rows.append(
            [
                types.InlineKeyboardButton(
                    text=f"{prefix}Фото {index} · #{image['id']}",
                    callback_data=f"admin_shop_set_primary:{article}:{image['id']}",
                )
            ]
        )
    rows.append(
        [
            types.InlineKeyboardButton(
                text="🔙 Назад", callback_data=f"admin_shop_back:{article}"
            )
        ]
    )
    await callback.message.edit_text(
        f"⭐ <b>Выберите главное фото</b>\n\nWB: <code>{article}</code>",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_shop_set_primary:"))
async def admin_shop_set_primary(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    _, article, image_id = callback.data.split(":", 2)
    success = await set_shop_product_primary_image(article, int(image_id))
    if not success:
        await callback.answer("Фото не найдено", show_alert=True)
        return
    await callback.message.edit_text(
        f"✅ Главное фото WB <code>{article}</code> обновлено.",
        reply_markup=get_admin_shop_keyboard(article),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_shop_back:"))
async def admin_shop_back_to_product(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    article = callback.data.split(":", 1)[1]
    await callback.message.edit_text(
        f"🛍 <b>Товар WB</b>: <code>{article}</code>\n\nЧто обновляем?",
        reply_markup=get_admin_shop_keyboard(article),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_shop_stock:"))
async def admin_shop_stock_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    article = callback.data.split(":", 1)[1]
    await state.update_data(shop_article=article)
    await callback.message.edit_text(
        f"📦 <b>Остаток товара</b>\n\nWB: <code>{article}</code>\n\n"
        "Введите общий остаток для мини-магазина:",
        reply_markup=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )
    await state.set_state(AdminStates.waiting_shop_stock)


@router.message(AdminStates.waiting_shop_stock)
async def admin_shop_stock_save(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        stock = int(message.text)
        if stock < 0:
            raise ValueError
    except (TypeError, ValueError):
        await message.answer("❌ Введите число 0 или больше:")
        return

    data = await state.get_data()
    article = data.get("shop_article")
    await upsert_shop_product_override(
        article, stock_override=stock, updated_by=message.from_user.id
    )
    await message.answer(
        f"✅ Остаток WB <code>{article}</code>: <code>{stock}</code>.",
        reply_markup=get_admin_shop_keyboard(article),
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data.startswith("admin_shop_price:"))
async def admin_shop_price_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    article = callback.data.split(":", 1)[1]
    await state.update_data(shop_article=article)
    await callback.message.edit_text(
        f"💰 <b>Цена товара</b>\n\nWB: <code>{article}</code>\n\n"
        "Введите цену в рублях для мини-магазина:",
        reply_markup=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )
    await state.set_state(AdminStates.waiting_shop_price)


@router.message(AdminStates.waiting_shop_price)
async def admin_shop_price_save(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        price = float(str(message.text).replace(",", "."))
        if price <= 0:
            raise ValueError
    except (TypeError, ValueError):
        await message.answer("❌ Введите цену числом:")
        return

    data = await state.get_data()
    article = data.get("shop_article")
    await upsert_shop_product_override(
        article, price_override=price, updated_by=message.from_user.id
    )
    await message.answer(
        f"✅ Цена WB <code>{article}</code>: <code>{price:.0f} ₽</code>.",
        reply_markup=get_admin_shop_keyboard(article),
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data == "admin_shop_orders")
async def admin_shop_orders(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    orders = await get_recent_shop_orders(10)
    if not orders:
        text = "📦 <b>Заказы магазина</b>\n\nПока заказов нет."
    else:
        parts = ["📦 <b>Последние заказы магазина</b>"]
        for order in orders:
            items = ", ".join(
                f"{item['wb_article']}×{item['qty']}" for item in order["items"]
            )
            parts.append(
                f"\n<b>{order['order_id']}</b>\n"
                f"👤 <code>{order['telegram_id'] or '-'}</code> · {order['customer_name'] or '-'}\n"
                f"📍 {order['city'] or '-'}, {order['address'] or '-'}\n"
                f"🚚 {order['delivery_method']} / {order['delivery_status']}\n"
                f"🛒 {items}\n"
                f"💰 <code>{order['total_rub']:.0f} ₽</code>"
            )
        text = "\n".join(parts)

    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_users")
async def admin_users_menu(callback: types.CallbackQuery, state: FSMContext):
    """Меню управления пользователями"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await callback.message.edit_text(
        "👥 <b>Управление пользователями</b>\n\n" "Введите Telegram ID пользователя:",
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
        f"➕ <b>Добавление кредитов</b>\n\n"
        f"Пользователь ID: <code>{user_id}</code>\n\n"
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
        f"➖ <b>Списание кредитов</b>\n\n"
        f"Пользователь ID: <code>{user_id}</code>\n\n"
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
        success = await add_credits(user_id, amount)
        action_text = f"добавлено <code>{amount}</code> кредитов"
    else:
        # Для списания нужно реализовать deduct_credits_by_admin
        from bot.database import deduct_credits

        success = await deduct_credits(user_id, amount)
        action_text = f"списано <code>{amount}</code> кредитов"

    if success:
        stats = await get_user_stats(user_id)
        await message.answer(
            f"✅ <b>Успешно!</b>\n\n"
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
        "📢 <b>Рассылка всем пользователям</b>\n\n"
        "Введите текст сообщения для рассылки:\n"
        "<i>Поддерживается HTML-форматирование</i>",
        reply_markup=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_broadcast_text)


@router.message(AdminStates.waiting_broadcast_text)
async def admin_process_broadcast_text(message: types.Message, state: FSMContext):
    """Показывает превью рассылки"""
    await state.update_data(broadcast_text=message.text)

    await message.answer(
        "📢 <b>Превью рассылки:</b>\n\n"
        "───────────────\n"
        f"{message.text}\n"
        "───────────────\n\n"
        "Подтверждаете отправку?",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="✅ Отправить", callback_data="admin_broadcast_confirm"
                    ),
                    types.InlineKeyboardButton(
                        text="❌ Отмена", callback_data="admin_back"
                    ),
                ]
            ]
        ),
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

    await callback.message.edit_text(
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
            await bot.send_message(
                user["telegram_id"], broadcast_text, parse_mode="HTML"
            )
            success_count += 1
        except Exception as e:
            logger.warning(f"Broadcast failed for {user['telegram_id']}: {e}")
            error_count += 1

    await callback.message.edit_text(
        f"📢 <b>Рассылка завершена!</b>\n\n"
        f"✅ Успешно: <code>{success_count}</code>\n"
        f"❌ Ошибок: <code>{error_count}</code>",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML",
    )

    await state.clear()


@router.callback_query(F.data == "admin_back")
async def admin_back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    """Возврат в админ-меню"""
    await state.clear()
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
