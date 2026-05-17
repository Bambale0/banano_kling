import logging
import os
import uuid
import json
import tempfile
from pathlib import Path

from aiogram import Bot, F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.database import (
    add_credits,
    add_shop_product_image,
    admin_adjust_user_credits,
    deduct_credits,
    get_admin_finance_overview,
    get_admin_recent_transactions,
    get_admin_stats,
    get_admin_user_profile,
    get_admin_users_page,
    get_recent_shop_orders,
    get_shop_product_images,
    get_user_stats,
    set_shop_product_primary_image,
    upsert_shop_product_override,
)
from bot.keyboards import get_admin_keyboard, get_back_keyboard
from bot.services.preset_manager import preset_manager
from bot.states import AdminStates

logger = logging.getLogger(__name__)
router = Router()
PRICE_PATH = Path(__file__).resolve().parents[2] / "data" / "price.json"


def _admin_root_text(stats: dict) -> str:
    return f"""
🔧 <b>Админ-панель</b>

📊 <b>Сейчас:</b>
• Пользователей: <code>{stats['total_users']}</code>
• Генераций: <code>{stats['total_generations']}</code>
• Транзакций: <code>{stats['total_transactions']}</code>
• Выручка: <code>{stats['total_revenue']:.0f}</code> ₽

Выберите раздел:
"""


def _price_config() -> dict:
    with open(PRICE_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def _save_price_config(data: dict) -> None:
    PRICE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=PRICE_PATH.parent, delete=False
    ) as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
        tmp_name = file.name
    os.replace(tmp_name, PRICE_PATH)
    preset_manager.reload()
    try:
        import bot.keyboards as keyboards

        keyboards.PRICES = keyboards.load_prices()
        keyboards.IMAGE_COSTS = keyboards.PRICES.get("costs_reference", {}).get(
            "image_models", keyboards.IMAGE_COSTS
        )
        keyboards.VIDEO_COSTS = keyboards.PRICES.get("costs_reference", {}).get(
            "video_models", keyboards.VIDEO_COSTS
        )
        keyboards.PACKAGES = keyboards.PRICES.get("packages", [])
    except Exception:
        logger.exception("Failed to refresh keyboard price cache")


def get_admin_users_keyboard(offset: int = 0):
    rows = [
        [types.InlineKeyboardButton(text="🔎 Найти по Telegram ID", callback_data="admin_user_search")]
    ]
    nav = []
    if offset > 0:
        nav.append(
            types.InlineKeyboardButton(
                text="⬅️ Назад", callback_data=f"admin_users_page:{max(0, offset - 10)}"
            )
        )
    nav.append(
        types.InlineKeyboardButton(
            text="➡️ Далее", callback_data=f"admin_users_page:{offset + 10}"
        )
    )
    rows.append(nav)
    rows.append([types.InlineKeyboardButton(text="🔙 В админку", callback_data="admin_back")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def get_admin_user_keyboard(telegram_id: int):
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="➕ Пополнить", callback_data=f"admin_add_credits_{telegram_id}"
                ),
                types.InlineKeyboardButton(
                    text="➖ Списать", callback_data=f"admin_deduct_credits_{telegram_id}"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="🎯 Установить баланс", callback_data=f"admin_set_credits_{telegram_id}"
                )
            ],
            [types.InlineKeyboardButton(text="👥 К списку", callback_data="admin_users")],
            [types.InlineKeyboardButton(text="🔙 В админку", callback_data="admin_back")],
        ]
    )


def get_admin_prices_keyboard():
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="📦 Пакеты GOE", callback_data="admin_prices_packages")],
            [types.InlineKeyboardButton(text="🖼 Модели изображений", callback_data="admin_prices_images")],
            [types.InlineKeyboardButton(text="🎬 Модели видео", callback_data="admin_prices_videos")],
            [types.InlineKeyboardButton(text="🔙 В админку", callback_data="admin_back")],
        ]
    )


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

    await message.answer(
        _admin_root_text(stats), reply_markup=get_admin_keyboard(), parse_mode="HTML"
    )


@router.callback_query(F.data == "admin_reload")
async def admin_reload_presets(callback: types.CallbackQuery):
    """Перезагружает пресеты из JSON"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    preset_manager.reload()
    await callback.answer(
        "✅ Конфиг и цены перечитаны",
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


@router.callback_query(F.data == "admin_finance")
async def admin_finance(callback: types.CallbackQuery):
    """Финансовая сводка."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    overview = await get_admin_finance_overview()
    transactions = await get_admin_recent_transactions(7)
    lines = [
        "💳 <b>Финансы</b>",
        "",
        f"Сегодня: <code>{overview['today_rub']:.0f} ₽</code>",
        f"7 дней: <code>{overview['week_rub']:.0f} ₽</code>",
        f"30 дней: <code>{overview['month_rub']:.0f} ₽</code>",
        f"Всего оплачено: <code>{overview['completed_rub']:.0f} ₽</code>",
        f"Оплаченных платежей: <code>{overview['completed_count']}</code>",
        f"Продано GOE: <code>{overview['sold_credits']}</code>",
        f"GOE на балансах: <code>{overview['credits_on_users']}</code>",
        f"GOE списано в задачах: <code>{overview['spent_credits']}</code>",
        f"Pending платежи: <code>{overview['pending_count']}</code> / <code>{overview['pending_rub']:.0f} ₽</code>",
        f"Задачи: <code>{overview['completed_tasks']}</code> готово, <code>{overview['pending_tasks']}</code> pending",
    ]
    if transactions:
        lines.append("\n<b>Последние платежи:</b>")
        for tx in transactions:
            lines.append(
                f"• <code>{tx['telegram_id'] or '-'}</code> · {tx['status']} · "
                f"{tx['amount_rub']:.0f} ₽ · {tx['credits']} GOE · {tx['provider']}"
            )

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )


def _format_admin_user_profile(profile: dict) -> str:
    return (
        "👤 <b>Пользователь</b>\n\n"
        f"Telegram ID: <code>{profile['telegram_id']}</code>\n"
        f"Баланс: <code>{profile['credits']}</code> GOE\n"
        f"Генераций: <code>{profile['generation_tasks']}</code>\n"
        f"Списано GOE: <code>{profile['generation_spent']}</code>\n"
        f"Оплат: <code>{profile['payments_count']}</code>\n"
        f"Выручка: <code>{profile['payments_rub']:.0f} ₽</code>\n"
        f"Рефералов: <code>{profile['referrals_count']}</code>\n"
        f"Реф.код: <code>{profile['referral_code'] or '-'}</code>\n"
        f"Партнёрский баланс: <code>{profile['partner_balance_rub']:.0f} ₽</code>\n"
        f"Создан: <code>{profile['created_at']}</code>\n"
        f"Обновлён: <code>{profile['updated_at']}</code>"
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

    page = await get_admin_users_page(limit=10, offset=0)
    lines = [
        "👥 <b>Пользователи</b>",
        "",
        f"Всего: <code>{page['total']}</code>",
        "",
    ]
    for user in page["users"]:
        lines.append(
            f"• <code>{user['telegram_id']}</code> · "
            f"{int(user['credits'] or 0)} GOE · "
            f"{int(user['generation_tasks'] or 0)} ген. · "
            f"{float(user['payments_rub'] or 0):.0f} ₽"
        )

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=get_admin_users_keyboard(0),
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data.startswith("admin_users_page:"))
async def admin_users_page(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    offset = int(callback.data.split(":", 1)[1])
    page = await get_admin_users_page(limit=10, offset=offset)
    lines = [
        "👥 <b>Пользователи</b>",
        "",
        f"Всего: <code>{page['total']}</code>",
        f"Страница: <code>{offset + 1}-{min(offset + page['limit'], page['total'])}</code>",
        "",
    ]
    for user in page["users"]:
        lines.append(
            f"• <code>{user['telegram_id']}</code> · "
            f"{int(user['credits'] or 0)} GOE · "
            f"{int(user['generation_tasks'] or 0)} ген. · "
            f"{float(user['payments_rub'] or 0):.0f} ₽"
        )

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=get_admin_users_keyboard(offset),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_user_search")
async def admin_user_search_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    await callback.message.edit_text(
        "🔎 <b>Поиск пользователя</b>\n\nВведите Telegram ID:",
        reply_markup=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )
    await state.set_state(AdminStates.waiting_user_search)


@router.message(AdminStates.waiting_user_search)
async def admin_process_user_search(message: types.Message, state: FSMContext):
    await admin_process_user_id(message, state)


@router.message(AdminStates.waiting_user_id)
async def admin_process_user_id(message: types.Message, state: FSMContext):
    """Обрабатывает ввод ID пользователя"""
    if not is_admin(message.from_user.id):
        return
    try:
        user_id = int(message.text)
    except ValueError:
        await message.answer("❌ Неверный формат ID. Введите число:")
        return

    profile = await get_admin_user_profile(user_id)
    if not profile:
        await message.answer(f"❌ Пользователь с ID {user_id} не найден.")
        return

    await state.update_data(target_user_id=user_id)

    await message.answer(
        _format_admin_user_profile(profile),
        reply_markup=get_admin_user_keyboard(user_id),
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


@router.callback_query(F.data.startswith("admin_set_credits_"))
async def admin_set_credits_prompt(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает новый баланс пользователя."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    user_id = int(callback.data.replace("admin_set_credits_", ""))
    await state.update_data(target_user_id=user_id, action="set")

    await callback.message.edit_text(
        f"🎯 <b>Установка баланса</b>\n\n"
        f"Пользователь ID: <code>{user_id}</code>\n\n"
        f"Введите новый баланс GOE:",
        reply_markup=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_credits_amount)


@router.message(AdminStates.waiting_credits_amount)
async def admin_process_credits_amount(message: types.Message, state: FSMContext):
    """Обрабатывает ввод количества кредитов"""
    try:
        amount = int(message.text)
        if amount < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Неверное количество. Введите целое число 0 или больше:")
        return

    data = await state.get_data()
    user_id = data.get("target_user_id")
    action = data.get("action")
    profile = await get_admin_user_profile(user_id)
    if not profile:
        await message.answer("❌ Пользователь не найден.", reply_markup=get_admin_keyboard())
        await state.clear()
        return

    if action == "add":
        success = await admin_adjust_user_credits(user_id, amount)
        action_text = f"добавлено <code>{amount}</code> GOE"
    elif action == "set":
        delta = amount - int(profile["credits"])
        success = await admin_adjust_user_credits(user_id, delta)
        action_text = f"установлен баланс <code>{amount}</code> GOE"
    else:
        success = await admin_adjust_user_credits(user_id, -amount)
        action_text = f"списано <code>{amount}</code> GOE"

    if success:
        profile = await get_admin_user_profile(user_id)
        await message.answer(
            f"✅ <b>Успешно!</b>\n\n"
            f"Пользователь ID: <code>{user_id}</code>\n"
            f"Действие: {action_text}\n"
            f"Текущий баланс: <code>{profile['credits']}</code> GOE",
            reply_markup=get_admin_user_keyboard(user_id),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            f"❌ Ошибка! Возможно, недостаточно кредитов для списания.",
            reply_markup=get_admin_keyboard(),
        )

    await state.clear()


@router.callback_query(F.data == "admin_prices")
async def admin_prices(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    data = _price_config()
    packages = data.get("packages", [])
    image_models = data.get("costs_reference", {}).get("image_models", {})
    video_models = data.get("costs_reference", {}).get("video_models", {})
    text = (
        "💎 <b>Управление ценами</b>\n\n"
        f"Пакетов: <code>{len(packages)}</code>\n"
        f"Моделей изображений: <code>{len(image_models)}</code>\n"
        f"Моделей видео: <code>{len(video_models)}</code>\n\n"
        "Выберите, что редактируем:"
    )
    await callback.message.edit_text(
        text, reply_markup=get_admin_prices_keyboard(), parse_mode="HTML"
    )
    await state.clear()


@router.callback_query(F.data == "admin_prices_packages")
async def admin_prices_packages(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    data = _price_config()
    rows = []
    lines = ["📦 <b>Пакеты GOE</b>\n"]
    for package in data.get("packages", []):
        package_id = package["id"]
        lines.append(
            f"• <code>{package_id}</code>: {package.get('credits', 0)} GOE за "
            f"{package.get('price_rub', 0)} ₽"
        )
        rows.append(
            [
                types.InlineKeyboardButton(
                    text=f"{package.get('name', package_id)}",
                    callback_data=f"admin_price_pkg:{package_id}",
                )
            ]
        )
    rows.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_prices")])
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_prices_images")
async def admin_prices_images(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    image_models = _price_config().get("costs_reference", {}).get("image_models", {})
    rows = []
    lines = ["🖼 <b>Цены изображений</b>\n"]
    for key, value in sorted(image_models.items()):
        lines.append(f"• <code>{key}</code>: <code>{value}</code> GOE")
        rows.append(
            [types.InlineKeyboardButton(text=f"{key}: {value}", callback_data=f"admin_price_img:{key}")]
        )
    rows.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_prices")])
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_prices_videos")
async def admin_prices_videos(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    video_models = _price_config().get("costs_reference", {}).get("video_models", {})
    rows = []
    lines = ["🎬 <b>Цены видео</b>\n"]
    for key, config_row in sorted(video_models.items()):
        durations = config_row.get("duration_costs", {})
        compact = ", ".join(f"{sec}s={cost}" for sec, cost in durations.items())
        lines.append(f"• <code>{key}</code>: {compact or config_row.get('base', '-')}")
        rows.append(
            [types.InlineKeyboardButton(text=key, callback_data=f"admin_price_vid:{key}")]
        )
    rows.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_prices")])
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_price_pkg:"))
async def admin_price_package_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    package_id = callback.data.split(":", 1)[1]
    package = next(
        (item for item in _price_config().get("packages", []) if item.get("id") == package_id),
        None,
    )
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return
    await state.update_data(price_target=("package", package_id))
    await callback.message.edit_text(
        f"📦 <b>{package.get('name', package_id)}</b>\n\n"
        f"Сейчас: <code>{package.get('credits', 0)} GOE</code> за "
        f"<code>{package.get('price_rub', 0)} ₽</code>\n\n"
        "Введите новые значения в формате:\n"
        "<code>credits price_rub</code>\n\n"
        "Например: <code>50 400</code>",
        reply_markup=get_back_keyboard("admin_prices"),
        parse_mode="HTML",
    )
    await state.set_state(AdminStates.waiting_price_value)


@router.callback_query(F.data.startswith("admin_price_img:"))
async def admin_price_image_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    key = callback.data.split(":", 1)[1]
    current = _price_config().get("costs_reference", {}).get("image_models", {}).get(key)
    await state.update_data(price_target=("image", key))
    await callback.message.edit_text(
        f"🖼 <b>{key}</b>\n\n"
        f"Сейчас: <code>{current}</code> GOE\n\n"
        "Введите новую цену GOE целым числом:",
        reply_markup=get_back_keyboard("admin_prices"),
        parse_mode="HTML",
    )
    await state.set_state(AdminStates.waiting_price_value)


@router.callback_query(F.data.startswith("admin_price_vid:"))
async def admin_price_video_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    key = callback.data.split(":", 1)[1]
    current = (
        _price_config().get("costs_reference", {}).get("video_models", {}).get(key, {})
    )
    await state.update_data(price_target=("video", key))
    durations = current.get("duration_costs", {})
    compact = " ".join(f"{sec}={cost}" for sec, cost in durations.items())
    await callback.message.edit_text(
        f"🎬 <b>{key}</b>\n\n"
        f"Сейчас: <code>{compact}</code>\n\n"
        "Введите цены длительностей в формате:\n"
        "<code>5=15 10=30 15=45</code>",
        reply_markup=get_back_keyboard("admin_prices"),
        parse_mode="HTML",
    )
    await state.set_state(AdminStates.waiting_price_value)


@router.message(AdminStates.waiting_price_value)
async def admin_process_price_value(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    target = data.get("price_target")
    if not target:
        await message.answer("❌ Цель редактирования потеряна. Откройте /admin заново.")
        await state.clear()
        return
    target_type, key = target
    raw = (message.text or "").strip()
    config_data = _price_config()

    try:
        if target_type == "package":
            credits_text, price_text = raw.replace(",", ".").split()[:2]
            credits = int(credits_text)
            price_rub = float(price_text)
            if credits <= 0 or price_rub <= 0:
                raise ValueError
            for package in config_data.get("packages", []):
                if package.get("id") == key:
                    package["credits"] = credits
                    package["price_rub"] = price_rub
                    break
            result_text = f"Пакет <code>{key}</code>: {credits} GOE за {price_rub:.0f} ₽"
        elif target_type == "image":
            value = int(raw)
            if value < 0:
                raise ValueError
            config_data.setdefault("costs_reference", {}).setdefault("image_models", {})[key] = value
            result_text = f"Модель <code>{key}</code>: {value} GOE"
        else:
            duration_costs = {}
            for chunk in raw.split():
                duration_text, cost_text = chunk.split("=", 1)
                duration = int(duration_text)
                cost = int(cost_text)
                if duration <= 0 or cost < 0:
                    raise ValueError
                duration_costs[str(duration)] = cost
            if not duration_costs:
                raise ValueError
            model_config = config_data.setdefault("costs_reference", {}).setdefault(
                "video_models", {}
            ).setdefault(key, {})
            model_config["duration_costs"] = duration_costs
            first_duration = min(int(item) for item in duration_costs)
            model_config["base"] = duration_costs[str(first_duration)]
            model_config["per_second_cost"] = round(
                duration_costs[str(first_duration)] / first_duration, 3
            )
            result_text = f"Видео <code>{key}</code>: " + ", ".join(
                f"{sec}s={cost}" for sec, cost in duration_costs.items()
            )
    except Exception:
        await message.answer(
            "❌ Не смог разобрать значение. Проверьте формат и попробуйте ещё раз."
        )
        return

    _save_price_config(config_data)
    await message.answer(
        f"✅ Цена обновлена.\n\n{result_text}",
        reply_markup=get_admin_prices_keyboard(),
        parse_mode="HTML",
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

    await callback.message.edit_text(
        _admin_root_text(stats), reply_markup=get_admin_keyboard(), parse_mode="HTML"
    )
