from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_main_menu_keyboard(user_credits: int = 0):
    """Главное меню с опциональной кнопкой PRO"""
    builder = InlineKeyboardBuilder()

    builder.button(text="🖼 Генерация фото", callback_data="cat_image_generation")
    builder.button(text="✏️ Редактировать фото", callback_data="cat_image_editing")
    builder.button(text="🎬 Генерация видео", callback_data="cat_video_generation")
    builder.button(text="✂️ Видео-эффекты", callback_data="cat_video_editing")

    # PRO-функция — пакетная генерация (доступно при 20+ кредитах)
    if user_credits >= 20:
        builder.button(text="⚡ ПАКЕТНАЯ ГЕНЕРАЦИЯ PRO", callback_data="menu_batch_pro")

    builder.button(text="💳 Пополнить баланс", callback_data="menu_buy_credits")
    builder.button(text="📊 Мой баланс", callback_data="menu_balance")
    builder.button(text="❓ Помощь", callback_data="menu_help")

    if user_credits >= 20:
        builder.adjust(2, 2, 1, 2, 1)
    else:
        builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def get_category_keyboard(category: str, presets: list, user_credits: int):
    """Клавиатура выбора пресета в категории"""
    builder = InlineKeyboardBuilder()
    
    for preset in presets:
        affordable = "✅" if user_credits >= preset.cost else "❌"
        builder.button(
            text=f"{preset.name} — {preset.cost}🍌 {affordable}",
            callback_data=f"preset_{preset.id}"
        )
    
    builder.button(text="🔙 Назад в меню", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def get_preset_action_keyboard(preset_id: str, has_input: bool):
    """Действия с выбранным пресетом"""
    builder = InlineKeyboardBuilder()

    if has_input:
        builder.button(
            text="✏️ Ввести свой вариант", callback_data=f"custom_{preset_id}"
        )
        builder.button(
            text="🎲 Использовать пример", callback_data=f"default_{preset_id}"
        )
    else:
        builder.button(text="▶️ Запустить генерацию", callback_data=f"run_{preset_id}")

    builder.button(text="🔙 Назад", callback_data=f"back_cat_{preset_id.split('_')[0]}")
    builder.adjust(1)
    return builder.as_markup()


def get_payment_packages_keyboard(packages: list):
    """Клавиатура выбора пакета бананов"""
    builder = InlineKeyboardBuilder()

    for pkg in packages:
        popular = "🔥 " if pkg.get("popular") else ""
        builder.button(
            text=f"{popular}{pkg['name']}: {pkg['credits']+pkg.get('bonus_credits',0)}🍌 за {pkg['price_rub']}₽",
            callback_data=f"buy_{pkg['id']}",
        )

    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def get_payment_confirmation_keyboard(payment_url: str, order_id: str):
    """Клавиатура подтверждения оплаты"""
    builder = InlineKeyboardBuilder()

    builder.button(text="💳 Перейти к оплате", url=payment_url)
    builder.button(
        text="✅ Я оплатил (проверить)", callback_data=f"check_payment_{order_id}"
    )
    builder.button(text="❌ Отменить", callback_data="cancel_payment")

    builder.adjust(1)
    return builder.as_markup()


def get_admin_keyboard():
    """Админ-панель"""
    builder = InlineKeyboardBuilder()

    builder.button(text="🔄 Перезагрузить пресеты", callback_data="admin_reload")
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="👥 Пользователи", callback_data="admin_users")
    builder.button(text="⚙️ Рассылка", callback_data="admin_broadcast")

    builder.adjust(2)
    return builder.as_markup()


def get_back_keyboard(callback_data: str = "back_main"):
    """Простая кнопка назад"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data=callback_data)
    return builder.as_markup()


def get_confirm_keyboard(confirm_data: str, cancel_data: str):
    """Клавиатура подтверждения действия"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=confirm_data)
    builder.button(text="❌ Отмена", callback_data=cancel_data)
    builder.adjust(2)
    return builder.as_markup()
