import logging
import random
from typing import Any as Message

from vkbottle import BotBlueprint as Blueprint
from vkbottle import Callback
from vkbottle.framework.labeler.base import ABCRule

from bot.keyboards import InlineKeyboardBuilder
from bot.vk_rules import PayloadEq, PayloadStartsWith, TextStartsWith


def random_id():
    return random.randint(-2147483648, 2147483647)


from bot.config import config
from bot.database import (
    add_credits,
    get_admin_stats,
    get_or_create_user,
    get_user_stats,
)
from bot.keyboards import get_admin_keyboard, get_back_keyboard
from bot.states import AdminStates

logger = logging.getLogger(__name__)
admin_bp = Blueprint("admin")


def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором"""
    return config.is_admin(user_id)


@admin_bp.on.message(TextStartsWith("/admin"))
async def cmd_admin(m: Message):
    """Открывает админ-панель"""
    if not is_admin(m.from_id):
        await m.answer("⛔ У вас нет доступа к админ-панели.")
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

    await m.answer(text, keyboard=get_admin_keyboard(), parse_mode="HTML")


@admin_bp.on.message(PayloadEq("admin_reload"))
async def admin_reload_presets(c: Callback):
    """Перезагружает пресеты из JSON"""
    if not is_admin(c.from_id):
        await c.answer("⛔ Нет доступа")
        return

    # Пресеты теперь не используются
    try:
        await c.answer(
            "✅ Пресеты отключены в этой версии",
            show_alert=True,
        )
    except:
        pass


@admin_bp.on.message(PayloadEq("admin_stats"))
async def admin_show_stats(c: Callback):
    """Показывает детальную статистику"""
    if not is_admin(c.from_id):
        await c.answer("⛔ Нет доступа")
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

    await c.message.edit_text(
        text, keyboard=get_back_keyboard("admin_back"), parse_mode="HTML"
    )


@admin_bp.on.message(PayloadEq("admin_users"))
async def admin_users_menu(c: Callback, state):
    """Меню управления пользователями"""
    if not is_admin(c.from_id):
        await c.answer("⛔ Нет доступа")
        return

    await c.message.edit_text(
        "👥 <b>Управление пользователями</b>\n\n" "Введите VK ID пользователя:",
        keyboard=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_user_id)


@admin_bp.on.message(state=AdminStates.waiting_user_id)
async def admin_process_user_id(m: Message, state):
    """Обрабатывает ввод ID пользователя"""
    try:
        user_id = int(m.text)
    except ValueError:
        await m.answer("❌ Неверный формат ID. Введите число:")
        return

    # Получаем статистику пользователя
    try:
        stats = await get_user_stats(user_id)
    except:
        await m.answer(f"❌ Пользователь с ID {user_id} не найден.")
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

    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить кредиты", payload=f"admin_add_credits_{user_id}")
    kb.button(text="➖ Списать кредиты", payload=f"admin_deduct_credits_{user_id}")
    kb.button(text="🔙 Назад", payload="admin_back")
    kb.adjust(1)

    await m.answer(
        text,
        keyboard=kb.build(),
        parse_mode="HTML",
    )

    await state.clear()


@admin_bp.on.message(PayloadStartsWith("admin_add_credits_"))
async def admin_add_credits_prompt(c: Callback, state):
    """Запрашивает количество кредитов для добавления"""
    if not is_admin(c.from_id):
        await c.answer("⛔ Нет доступа")
        return

    user_id = int(c.payload.replace("admin_add_credits_", ""))
    await state.update_data(target_user_id=user_id, action="add")

    await c.message.edit_text(
        f"➕ <b>Добавление кредитов</b>\n\n"
        f"Пользователь ID: <code>{user_id}</code>\n\n"
        f"Введите количество кредитов для добавления:",
        keyboard=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_credits_amount)


@admin_bp.on.message(PayloadStartsWith("admin_deduct_credits_"))
async def admin_deduct_credits_prompt(c: Callback, state):
    """Запрашивает количество кредитов для списания"""
    if not is_admin(c.from_id):
        await c.answer("⛔ Нет доступа")
        return

    user_id = int(c.payload.replace("admin_deduct_credits_", ""))
    await state.update_data(target_user_id=user_id, action="deduct")

    await c.message.edit_text(
        f"➖ <b>Списание кредитов</b>\n\n"
        f"Пользователь ID: <code>{user_id}</code>\n\n"
        f"Введите количество кредитов для списания:",
        keyboard=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_credits_amount)


@admin_bp.on.message(state=AdminStates.waiting_credits_amount)
async def admin_process_credits_amount(m: Message, state):
    """Обрабатывает ввод количества кредитов"""
    try:
        amount = int(m.text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await m.answer("❌ Неверное количество. Введите положительное число:")
        return

    data = await state.get_data()
    user_id = data.get("target_user_id")
    action = data.get("action")

    if action == "add":
        success = await add_credits(user_id, amount)
        action_text = f"добавлено <code>{amount}</code> кредитов"
    else:
        # TODO: implement deduct_credits_by_admin if needed
        success = True  # Placeholder
        action_text = f"списано <code>{amount}</code> кредитов"

    if success:
        stats = await get_user_stats(user_id)
        await m.answer(
            f"✅ <b>Успешно!</b>\n\n"
            f"Пользователь ID: <code>{user_id}</code>\n"
            f"Действие: {action_text}\n"
            f"Текущий баланс: <code>{stats['credits']}</code> кредитов",
            keyboard=get_admin_keyboard(),
            parse_mode="HTML",
        )
    else:
        await m.answer(
            f"❌ Ошибка! Возможно, недостаточно кредитов для списания.",
            keyboard=get_admin_keyboard().build(),
        )

    await state.clear()


@admin_bp.on.message(PayloadEq("admin_broadcast"))
async def admin_broadcast_prompt(c: Callback, state):
    """Запрашивает текст рассылки"""
    if not is_admin(c.from_id):
        await c.answer("⛔ Нет доступа")
        return

    await c.message.edit_text(
        "📢 <b>Рассылка всем пользователям</b>\n\n"
        "Введите текст сообщения для рассылки:\n"
        "<i>Поддерживается HTML-форматирование</i>",
        keyboard=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_broadcast_text)


@admin_bp.on.message(state=AdminStates.waiting_broadcast_text)
async def admin_process_broadcast_text(m: Message, state):
    """Показывает превью рассылки"""
    await state.update_data(broadcast_text=m.text)

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Отправить", payload="admin_broadcast_confirm")
    kb.button(text="❌ Отмена", payload="admin_back")
    kb.adjust(2)

    await m.answer(
        "📢 <b>Превью рассылки:</b>\n\n"
        "───────────────\n"
        f"{m.text}\n"
        "───────────────\n\n"
        "Подтверждаете отправку?",
        keyboard=kb.build(),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.confirming_broadcast)


@admin_bp.on.message(PayloadEq("admin_broadcast_confirm"))
async def admin_execute_broadcast(c: Callback, state):
    """Выполняет рассылку"""
    if not is_admin(c.from_id):
        await c.answer("⛔ Нет доступа")
        return

    data = await state.get_data()
    broadcast_text = data.get("broadcast_text")

    await c.message.edit_text("📢 <b>Рассылка запущена...</b>", parse_mode="HTML")

    # Получаем всех пользователей
    import aiosqlite

    from bot.database import DATABASE_PATH

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT vk_user_id FROM users")
        users = await cursor.fetchall()

    success_count = 0
    error_count = 0

    api = c.api

    for user in users:
        try:
            await api.messages.send(
                user_id=user["vk_user_id"],
                message=broadcast_text,
                parse_mode="HTML",
                random_id=random_id(),
            )
            success_count += 1
        except Exception as e:
            logger.warning(f"Broadcast failed for {user['vk_user_id']}: {e}")
            error_count += 1

    await c.message.edit_text(
        f"📢 <b>Рассылка завершена!</b>\n\n"
        f"✅ Успешно: <code>{success_count}</code>\n"
        f"❌ Ошибок: <code>{error_count}</code>",
        keyboard=get_admin_keyboard(),
        parse_mode="HTML",
    )

    await state.clear()


@admin_bp.on.message(PayloadEq("admin_back"))
async def admin_back_to_menu(c: Callback):
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

    await c.message.edit_text(text, keyboard=get_admin_keyboard(), parse_mode="HTML")
