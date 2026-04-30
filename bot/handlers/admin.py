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
    get_back_keyboard,
    get_main_menu_button_keyboard,
)
from bot.services.preset_manager import preset_manager
from bot.states import AdminStates

logger = logging.getLogger(__name__)
router = Router()
PRICE_PATH = Path(config.PRICE_PATH)


def _admin_price_menu_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="📦 Пакеты пополнения", callback_data="admin_prices_packages"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🖼 Цены фото", callback_data="admin_prices_images"
                ),
                types.InlineKeyboardButton(
                    text="🎬 Цены видео", callback_data="admin_prices_videos"
                ),
            ],
            [types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
        ]
    )


def _chunk_buttons(
    buttons: list[types.InlineKeyboardButton], per_row: int = 1
) -> list[list[types.InlineKeyboardButton]]:
    return [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]


def _admin_packages_keyboard() -> types.InlineKeyboardMarkup:
    buttons = []
    for pkg in preset_manager.get_packages():
        buttons.append(
            types.InlineKeyboardButton(
                text=f"{pkg['name']} • {pkg['price_rub']}₽ / {pkg['credits']}🍌",
                callback_data=f"admin_price_package_{pkg['id']}",
            )
        )
    rows = _chunk_buttons(buttons) + [
        [types.InlineKeyboardButton(text="🔙 К разделам", callback_data="admin_prices")]
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_package_fields_keyboard(package_id: str) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="💳 Цена в ₽",
                    callback_data=f"admin_price_package_field_{package_id}_price_rub",
                ),
                types.InlineKeyboardButton(
                    text="🍌 Кол-во бананов",
                    callback_data=f"admin_price_package_field_{package_id}_credits",
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="🔙 К пакетам", callback_data="admin_prices_packages"
                )
            ],
        ]
    )


def _admin_image_prices_keyboard() -> types.InlineKeyboardMarkup:
    image_models = (
        preset_manager.get_price_config()
        .get("costs_reference", {})
        .get("image_models", {})
    )
    labels = {
        "nano-banana-pro": "Nano Banana Pro",
        "banana_2": "Nano Banana 2",
        "seedream_edit": "Seedream 4.5 Edit",
        "flux_pro": "GPT Image 2",
        "grok_imagine_i2i": "Grok Imagine",
        "wan_27": "Wan 2.7 Pro",
    }
    buttons = []
    for key, value in image_models.items():
        buttons.append(
            types.InlineKeyboardButton(
                text=f"{labels.get(key, key)} • {value}🍌",
                callback_data=f"admin_price_image_{key}",
            )
        )
    rows = _chunk_buttons(buttons) + [
        [types.InlineKeyboardButton(text="🔙 К разделам", callback_data="admin_prices")]
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_video_prices_keyboard() -> types.InlineKeyboardMarkup:
    video_models = (
        preset_manager.get_price_config()
        .get("costs_reference", {})
        .get("video_models", {})
    )
    labels = {
        "v3_std": "Kling v3",
        "v3_pro": "Kling 3.0",
        "v26_pro": "Kling 2.5 Turbo",
        "grok_imagine": "Grok Imagine",
        "veo3": "Veo 3.1 Quality",
        "veo3_fast": "Veo 3.1 Fast",
        "veo3_lite": "Veo 3.1 Lite",
        "glow": "Kling Glow",
        "v26_motion_pro": "Motion Pro",
    }
    buttons = []
    for model_key, model_cfg in video_models.items():
        duration_costs = (model_cfg or {}).get("duration_costs", {})
        if duration_costs:
            for duration, value in duration_costs.items():
                buttons.append(
                    types.InlineKeyboardButton(
                        text=f"{labels.get(model_key, model_key)} • {duration}с • {value}🍌",
                        callback_data=f"admin_price_video_{model_key}_{duration}",
                    )
                )
            continue

        base_value = (model_cfg or {}).get("base", (model_cfg or {}).get("cost"))
        if base_value is None:
            continue
        buttons.append(
            types.InlineKeyboardButton(
                text=f"{labels.get(model_key, model_key)} • {base_value}🍌",
                callback_data=f"admin_price_video_{model_key}_base",
            )
        )

    rows = _chunk_buttons(buttons) + [
        [types.InlineKeyboardButton(text="🔙 К разделам", callback_data="admin_prices")]
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _read_price_config() -> dict:
    with open(PRICE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_price_value(raw_value: str, current_value):
    raw_value = raw_value.strip().replace(",", ".")
    if isinstance(current_value, int):
        value = int(raw_value)
    else:
        value = float(raw_value)
        if value.is_integer():
            value = int(value)
    if value <= 0:
        raise ValueError
    return value


def _update_price_value(target: str, key: str, field: str, value):
    price_config = _read_price_config()

    if target == "package":
        packages = price_config.get("packages", [])
        package = next((pkg for pkg in packages if pkg.get("id") == key), None)
        if not package or field not in {"price_rub", "credits"}:
            raise KeyError("package")
        old_value = package[field]
        package[field] = value
        preset_manager.update_price_config(price_config)
        return old_value

    if target == "image":
        image_models = price_config["costs_reference"]["image_models"]
        if key not in image_models:
            raise KeyError("image")
        old_value = image_models[key]
        image_models[key] = value
        preset_manager.update_price_config(price_config)
        return old_value

    if target == "video":
        video_models = price_config["costs_reference"]["video_models"]
        model = video_models.get(key)
        if not model:
            raise KeyError("video")
        if field == "base":
            target_key = "base" if "base" in model else "cost"
            old_value = model[target_key]
            model[target_key] = value
        else:
            duration_costs = model.setdefault("duration_costs", {})
            old_value = duration_costs[field]
            duration_costs[field] = value
        preset_manager.update_price_config(price_config)
        return old_value

    raise KeyError(target)


def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором"""
    return config.is_admin(user_id)


@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    """Открывает админ-панель"""
    if not is_admin(message.from_user.id):
        await message.answer(
            "⛔ У вас нет доступа к админ-панели.",
            reply_markup=get_main_menu_button_keyboard(),
        )
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

    success = preset_manager.reload()
    await callback.answer(
        (
            "✅ Прайс и конфиг перезагружены"
            if success
            else "❌ Не удалось перезагрузить конфиг"
        ),
        show_alert=True,
    )


@router.callback_query(F.data == "admin_prices")
async def admin_prices_menu(callback: types.CallbackQuery, state: FSMContext):
    """Меню управления ценами."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await state.clear()
    await callback.message.edit_text(
        "💸 <b>Управление ценами</b>\n\n" "Выберите раздел, который нужно обновить.",
        reply_markup=_admin_price_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_prices_packages")
async def admin_prices_packages(callback: types.CallbackQuery):
    """Список пакетов пополнения."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await callback.message.edit_text(
        "📦 <b>Пакеты пополнения</b>\n\n"
        "Выберите пакет, чтобы поменять цену в рублях или количество бананов.",
        reply_markup=_admin_packages_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_prices_images")
async def admin_prices_images(callback: types.CallbackQuery):
    """Список цен на фото-модели."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await callback.message.edit_text(
        "🖼 <b>Цены на фото</b>\n\n"
        "Выберите модель и отправьте новую стоимость в бананах.",
        reply_markup=_admin_image_prices_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_prices_videos")
async def admin_prices_videos(callback: types.CallbackQuery):
    """Список цен на видео-модели."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await callback.message.edit_text(
        "🎬 <b>Цены на видео</b>\n\n"
        "Выберите модель или длительность и отправьте новую стоимость в бананах.",
        reply_markup=_admin_video_prices_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.regexp(r"^admin_price_package_[a-z0-9-]+$"))
async def admin_price_package(callback: types.CallbackQuery):
    """Выбор полей пакета для редактирования."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    package_id = callback.data.replace("admin_price_package_", "", 1)
    package = preset_manager.get_package(package_id)
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    await callback.message.edit_text(
        "📦 <b>Редактирование пакета</b>\n\n"
        f"Пакет: <code>{package['name']}</code>\n"
        f"Цена: <code>{package['price_rub']}</code> ₽\n"
        f"Бананы: <code>{package['credits']}</code> 🍌\n\n"
        "Что хотите изменить?",
        reply_markup=_admin_package_fields_keyboard(package_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_price_package_field_"))
async def admin_price_package_field(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает новое значение для поля пакета."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    prefix = "admin_price_package_field_"
    payload = callback.data[len(prefix) :]
    if payload.endswith("_price_rub"):
        package_id = payload[: -len("_price_rub")]
        field = "price_rub"
    elif payload.endswith("_credits"):
        package_id = payload[: -len("_credits")]
        field = "credits"
    else:
        package_id = payload
        field = ""
    package = preset_manager.get_package(package_id)
    if not package or field not in {"price_rub", "credits"}:
        await callback.answer("Некорректное поле", show_alert=True)
        return

    field_label = "цену в ₽" if field == "price_rub" else "количество бананов"
    current_value = package[field]
    await state.set_state(AdminStates.waiting_price_value)
    await state.update_data(
        price_target="package",
        price_key=package_id,
        price_field=field,
        current_price_value=current_value,
        return_to="admin_prices_packages",
    )

    await callback.message.edit_text(
        f"✏️ <b>Изменение пакета {package['name']}</b>\n\n"
        f"Текущее значение за {field_label}: <code>{current_value}</code>\n"
        "Отправьте новое число одним сообщением.",
        reply_markup=get_back_keyboard("admin_prices_packages"),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_price_image_"))
async def admin_price_image(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает новую цену для фото-модели."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    model_key = callback.data.replace("admin_price_image_", "", 1)
    image_models = (
        preset_manager.get_price_config()
        .get("costs_reference", {})
        .get("image_models", {})
    )
    current_value = image_models.get(model_key)
    if current_value is None:
        await callback.answer("Модель не найдена", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_price_value)
    await state.update_data(
        price_target="image",
        price_key=model_key,
        price_field="cost",
        current_price_value=current_value,
        return_to="admin_prices_images",
    )

    await callback.message.edit_text(
        f"🖼 <b>Изменение цены фото-модели</b>\n\n"
        f"Модель: <code>{model_key}</code>\n"
        f"Текущая стоимость: <code>{current_value}</code> 🍌\n\n"
        "Отправьте новую стоимость одним сообщением.",
        reply_markup=get_back_keyboard("admin_prices_images"),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_price_video_"))
async def admin_price_video(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает новую цену для видео-модели."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    payload = callback.data.replace("admin_price_video_", "", 1)
    model_key, field = payload.rsplit("_", 1)
    video_models = (
        preset_manager.get_price_config()
        .get("costs_reference", {})
        .get("video_models", {})
    )
    model = video_models.get(model_key)
    if not model:
        await callback.answer("Модель не найдена", show_alert=True)
        return

    current_value = (
        (model.get("duration_costs") or {}).get(field)
        if field != "base"
        else model.get("base", model.get("cost"))
    )
    if current_value is None:
        await callback.answer("Цена не найдена", show_alert=True)
        return

    label = "base" if field == "base" else f"{field} сек"
    await state.set_state(AdminStates.waiting_price_value)
    await state.update_data(
        price_target="video",
        price_key=model_key,
        price_field=field,
        current_price_value=current_value,
        return_to="admin_prices_videos",
    )

    await callback.message.edit_text(
        f"🎬 <b>Изменение цены видео-модели</b>\n\n"
        f"Модель: <code>{model_key}</code>\n"
        f"Параметр: <code>{label}</code>\n"
        f"Текущая стоимость: <code>{current_value}</code> 🍌\n\n"
        "Отправьте новую стоимость одним сообщением.",
        reply_markup=get_back_keyboard("admin_prices_videos"),
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_price_value)
async def admin_process_price_value(message: types.Message, state: FSMContext):
    """Сохраняет новое значение цены."""
    data = await state.get_data()
    target = data.get("price_target")
    key = data.get("price_key")
    field = data.get("price_field")
    current_value = data.get("current_price_value")
    return_to = data.get("return_to", "admin_prices")

    try:
        new_value = _parse_price_value(message.text or "", current_value)
        old_value = _update_price_value(target, key, field, new_value)
    except ValueError:
        await message.answer(
            "❌ Неверное значение. Отправьте положительное число.",
            reply_markup=get_back_keyboard(return_to),
        )
        return
    except Exception as e:
        logger.exception("Failed to update price: %s", e)
        await message.answer(
            "❌ Не удалось обновить цену.",
            reply_markup=get_back_keyboard(return_to),
        )
        await state.clear()
        return

    await message.answer(
        "✅ <b>Цена обновлена</b>\n\n"
        f"Было: <code>{old_value}</code>\n"
        f"Стало: <code>{new_value}</code>",
        reply_markup=get_back_keyboard(return_to),
        parse_mode="HTML",
    )
    await state.clear()


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
        await message.answer(
            "❌ Неверный формат ID. Введите число:",
            reply_markup=get_back_keyboard("admin_back"),
        )
        return

    # Получаем статистику пользователя
    try:
        stats = await get_user_stats(user_id)
    except Exception as e:
        logger.warning(f"User {user_id} not found: {e}")
        await message.answer(
            f"❌ Пользователь с ID {user_id} не найден.",
            reply_markup=get_back_keyboard("admin_back"),
        )
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
    """Показывает превью рассылки"""
    await state.update_data(broadcast_text=message.text)

    await message.answer(
        "📢 <b>Превью рассылки:</b>"
        "───────────────\n"
        f"{message.text}\n"
        "───────────────"
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
        f"📢 <b>Рассылка завершена!</b>"
        f"✅ Успешно: <code>{success_count}</code>\n"
        f"❌ Ошибок: <code>{error_count}</code>",
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
