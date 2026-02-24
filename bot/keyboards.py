from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu():
    """Упрощённое главное меню - все кнопки inline"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎨 Генерация изображения", callback_data="menu_image_gen")],
            [InlineKeyboardButton(text="✏️ Редактировать изображение", callback_data="menu_image_edit")],
            [InlineKeyboardButton(text="🎬 Генерация видео", callback_data="menu_video_gen")],
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings")],
        ]
    )


def settings_menu():
    """Меню настроек"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🤖 Модель ИИ", callback_data="setting_model")
    builder.button(text="📹 Качество видео", callback_data="setting_video")
    builder.button(text="🔙 Назад", callback_data="back_to_main")
    return builder.as_markup()


def model_selection(current_model: str = "flash"):
    """Выбор модели для генерации изображений"""
    flash_check = "✅ " if current_model == "flash" else ""
    pro_check = "✅ " if current_model == "pro" else ""
    
    builder = InlineKeyboardBuilder()
    builder.button(text=f"{flash_check}⚡ Flash (быстро)", callback_data="set_model_flash")
    builder.button(text=f"{pro_check}🎨 Pro (качество)", callback_data="set_model_pro")
    builder.button(text="🔙 Назад", callback_data="settings")
    return builder.as_markup()


def video_quality_selection(current_quality: str = "std"):
    """Выбор качества видео"""
    std_check = "✅ " if current_quality == "std" else ""
    pro_check = "✅ " if current_quality == "pro" else ""
    
    builder = InlineKeyboardBuilder()
    builder.button(text=f"{std_check}⚡ Standard (быстро)", callback_data="set_video_std")
    builder.button(text=f"{pro_check}🎬 Pro (качество)", callback_data="set_video_pro")
    builder.button(text="🔙 Назад", callback_data="settings")
    return builder.as_markup()


def aspect_ratio_keyboard():
    """Клавиатура выбора формата изображения"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1:1", callback_data="aspect_1:1"),
                InlineKeyboardButton(text="16:9", callback_data="aspect_16:9"),
                InlineKeyboardButton(text="9:16", callback_data="aspect_9:16"),
            ],
            [
                InlineKeyboardButton(text="4:3", callback_data="aspect_4:3"),
                InlineKeyboardButton(text="3:4", callback_data="aspect_3:4"),
                InlineKeyboardButton(text="2:3", callback_data="aspect_2:3"),
            ],
        ]
    )


def video_aspect_ratio_keyboard():
    """Клавиатура выбора формата видео"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="16:9 (широкий)", callback_data="video_aspect_16:9"),
                InlineKeyboardButton(text="9:16 (вертикальный)", callback_data="video_aspect_9:16"),
            ],
            [InlineKeyboardButton(text="1:1 (квадрат)", callback_data="video_aspect_1:1")],
        ]
    )


def video_duration_keyboard():
    """Клавиатура выбора длительности видео"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="3 сек", callback_data="duration_3"),
                InlineKeyboardButton(text="5 сек", callback_data="duration_5"),
                InlineKeyboardButton(text="7 сек", callback_data="duration_7"),
            ],
            [
                InlineKeyboardButton(text="10 сек", callback_data="duration_10"),
                InlineKeyboardButton(text="12 сек", callback_data="duration_12"),
                InlineKeyboardButton(text="15 сек", callback_data="duration_15"),
            ],
        ]
    )


def skip_prompt_keyboard():
    """Клавиатура для пропуска промпта"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_prompt")]
        ]
    )


def get_back_keyboard(callback_data: str = "back_main"):
    """Простая кнопка назад"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data=callback_data)
    return builder.as_markup()


# =============================================================================
# КЛАВИАТУРЫ ДЛЯ ПАКЕТНОЙ ГЕНЕРАЦИИ (ОПЦИОНАЛЬНО)
# =============================================================================

def batch_count_keyboard():
    """Выбор количества для пакетной генерации"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="2 шт", callback_data="batch_2"),
                InlineKeyboardButton(text="4 шт", callback_data="batch_4"),
            ],
            [
                InlineKeyboardButton(text="6 шт", callback_data="batch_6"),
                InlineKeyboardButton(text="8 шт", callback_data="batch_8"),
            ],
        ]
    )


def batch_edit_ready_keyboard(count: int = 0):
    """Готовность к обработке пакетного редактирования"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ Готово ({count} фото)", callback_data="batch_edit_ready")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="batch_edit_cancel")],
        ]
    )


def batch_edit_add_more_keyboard(count: int = 0):
    """Добавить ещё или готово"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📎 Добавить ещё", callback_data="batch_edit_add")],
            [InlineKeyboardButton(text=f"✅ Готово ({count})", callback_data="batch_edit_ready")],
        ]
    )


# =============================================================================
# СТАРЫЕ КЛАВИАТУРЫ (ДЛЯ СОВМЕСТИМОСТИ)
# =============================================================================

def get_main_menu_keyboard(user_credits: int = 0):
    """Главное меню с опциональной кнопкой PRO"""
    builder = InlineKeyboardBuilder()

    builder.button(text="🖼 Генерация фото", callback_data="cat_image_generation")
    builder.button(text="✏️ Редактировать фото", callback_data="cat_image_editing")
    builder.button(text="🎬 Генерация видео", callback_data="cat_video_generation")
    builder.button(text="✂️ Видео-эффекты", callback_data="cat_video_editing")

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
        if hasattr(preset, 'description') and preset.description:
            display_text = f"{preset.name}\n   📝 {preset.description[:40]}..."
        else:
            display_text = preset.name
        builder.button(
            text=f"{display_text} — {preset.cost}🍌 {affordable}",
            callback_data=f"preset_{preset.id}"
        )
    
    builder.button(text="🔙 Назад в меню", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def get_preset_action_keyboard(preset_id: str, has_input: bool, category: str = None):
    """Действия с выбранным пресетом"""
    builder = InlineKeyboardBuilder()

    if category in ["video_generation", "video_editing"]:
        builder.button(text="⏱ Длительность", callback_data=f"opt_duration_{preset_id}")
        builder.button(text="📐 Формат", callback_data=f"opt_ratio_{preset_id}")
        
    if has_input:
        builder.button(text="✏️ Ввести свой вариант", callback_data=f"custom_{preset_id}")
        builder.button(text="🎲 Использовать пример", callback_data=f"default_{preset_id}")
    else:
        builder.button(text="▶️ Запустить генерацию", callback_data=f"run_{preset_id}")

    builder.button(text="🔙 Назад", callback_data=f"back_cat_{preset_id.split('_')[0]}")
    
    if category in ["video_generation", "video_editing"]:
        builder.adjust(2, 2, 2, 1)
    else:
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
    builder.button(text="🔙 Назад", callback_data="menu_buy_credits")

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


def get_confirm_keyboard(confirm_data: str, cancel_data: str):
    """Клавиатура подтверждения действия"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=confirm_data)
    builder.button(text="❌ Отмена", callback_data=cancel_data)
    builder.adjust(2)
    return builder.as_markup()


def get_duration_keyboard(preset_id: str, current_duration: int = 5):
    """Клавиатура выбора длительности видео"""
    builder = InlineKeyboardBuilder()
    
    durations = [3, 5, 10, 15]
    
    for dur in durations:
        emoji = "✅" if dur == current_duration else ""
        builder.button(text=f"{dur} сек {emoji}", callback_data=f"duration_{preset_id}_{dur}")
    
    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    builder.adjust(2)
    return builder.as_markup()


def get_aspect_ratio_keyboard(preset_id: str, current_ratio: str = "16:9"):
    """Клавиатура выбора формата видео"""
    builder = InlineKeyboardBuilder()
    
    ratios = {
        "16:9": "📺 Landscape (YouTube)",
        "9:16": "📱 Vertical (TikTok/Reels)",
        "1:1": "⬜ Square (Instagram)"
    }
    
    for ratio, label in ratios.items():
        emoji = "✅" if ratio == current_ratio else ""
        builder.button(text=f"{label} {emoji}", callback_data=f"ratio_{preset_id}_{ratio}")
    
    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    builder.adjust(1)
    return builder.as_markup()


def get_video_options_keyboard(preset_id: str):
    """Клавиатура дополнительных опций видео"""
    builder = InlineKeyboardBuilder()
    
    builder.button(text="⏱ Длительность", callback_data=f"opt_duration_{preset_id}")
    builder.button(text="📐 Формат", callback_data=f"opt_ratio_{preset_id}")
    builder.button(text="🎵 Со звуком", callback_data=f"opt_audio_{preset_id}")
    
    builder.button(text="▶️ Запустить", callback_data=f"run_{preset_id}")
    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_quality_keyboard(preset_id: str):
    """Клавиатура выбора качества видео"""
    builder = InlineKeyboardBuilder()
    
    builder.button(
        text="⚡ Standard (быстрее, дешевле)",
        callback_data=f"quality_{preset_id}_std"
    )
    builder.button(
        text="💎 Pro (лучшее качество)",
        callback_data=f"quality_{preset_id}_pro"
    )
    
    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    builder.adjust(1)
    return builder.as_markup()


def get_model_selection_keyboard(preset_id: str, current_model: str = None):
    """Клавиатура выбора модели генерации"""
    builder = InlineKeyboardBuilder()
    
    flash_selected = "✅" if current_model and "flash" in current_model else ""
    builder.button(
        text=f"⚡ Nano Banana Flash {flash_selected}\n   Быстрая, до 1024px",
        callback_data=f"model_{preset_id}_flash"
    )
    
    pro_selected = "✅" if current_model and "pro" in current_model else ""
    builder.button(
        text=f"💎 Nano Banana Pro {pro_selected}\n   До 4K, с reasoning",
        callback_data=f"model_{preset_id}_pro"
    )
    
    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    builder.adjust(1)
    return builder.as_markup()


def get_resolution_keyboard(preset_id: str, current_resolution: str = "1K"):
    """Клавиатура выбора разрешения изображения"""
    builder = InlineKeyboardBuilder()
    
    resolutions = [
        ("1K", "⚡ Standard (1024px)", "1K"),
        ("2K", "💎 HD (2048px)", "2K"),
        ("4K", "👑 Ultra (4096px)", "4K")
    ]
    
    for res, label, _ in resolutions:
        emoji = "✅" if res == current_resolution else ""
        builder.button(text=f"{label} {emoji}", callback_data=f"resolution_{preset_id}_{res}")
    
    builder.button(text="🔙 Назад", callback_data=f"model_{preset_id}")
    builder.adjust(1)
    return builder.as_markup()


def get_image_aspect_ratio_keyboard(preset_id: str, current_ratio: str = "1:1"):
    """Клавиатура выбора формата изображения"""
    builder = InlineKeyboardBuilder()
    
    ratios = [
        ("1:1", "⬜ Квадрат"),
        ("16:9", "📺 Горизонтальный"),
        ("9:16", "📱 Вертикальный"),
        ("4:5", "📸 Портретный"),
        ("21:9", "🎬 Панорамный")
    ]
    
    for ratio, label in ratios:
        emoji = "✅" if ratio == current_ratio else ""
        builder.button(text=f"{label} ({ratio}) {emoji}", callback_data=f"img_ratio_{preset_id}_{ratio}")
    
    builder.button(text="🔙 Назад", callback_data=f"model_{preset_id}")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_reference_images_keyboard(preset_id: str):
    """Клавиатура для работы с референсными изображениями"""
    builder = InlineKeyboardBuilder()
    
    builder.button(text="🖼 Добавить референс (до 14)", callback_data=f"ref_add_{preset_id}")
    builder.button(text="👤 Добавить референс человека", callback_data=f"ref_person_{preset_id}")
    builder.button(text="📦 Показать загруженные", callback_data=f"ref_list_{preset_id}")
    builder.button(text="🗑 Очистить все", callback_data=f"ref_clear_{preset_id}")
    
    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    builder.adjust(1, 1, 2, 1)
    return builder.as_markup()


def get_search_grounding_keyboard(preset_id: str, enabled: bool = False):
    """Клавиатура для поискового заземления (Grounding)"""
    builder = InlineKeyboardBuilder()
    
    status = "🔴 ВЫКЛ" if enabled else "🟢 ВКЛ"
    builder.button(text=f"🔍 Поиск в интернете: {status}", callback_data=f"grounding_{preset_id}_toggle")
    
    if enabled:
        builder.button(text="ℹ️ Что это?", callback_data=f"grounding_info_{preset_id}")
    
    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    builder.adjust(1)
    return builder.as_markup()


def get_advanced_options_keyboard(preset_id: str):
    """Клавиатура расширенных опций генерации"""
    builder = InlineKeyboardBuilder()
    
    builder.button(text="🤖 Выбор модели", callback_data=f"model_{preset_id}")
    builder.button(text="📏 Формат изображения", callback_data=f"img_ratio_{preset_id}")
    builder.button(text="👁 Разрешение", callback_data=f"resolution_{preset_id}")
    builder.button(text="🖼 Референсы", callback_data=f"ref_{preset_id}")
    builder.button(text="🔍 Поиск в интернете", callback_data=f"grounding_{preset_id}")
    
    builder.button(text="▶️ Запустить генерацию", callback_data=f"run_{preset_id}")
    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def get_image_editing_options_keyboard(preset_id: str):
    """Клавиатура опций редактирования изображений"""
    builder = InlineKeyboardBuilder()
    
    builder.button(text="🎭 Сменить стиль", callback_data=f"edit_style_{preset_id}")
    builder.button(text="➕ Добавить объект", callback_data=f"edit_add_{preset_id}")
    builder.button(text="➖ Удалить объект", callback_data=f"edit_remove_{preset_id}")
    builder.button(text="🔄 Заменить элемент", callback_data=f"edit_replace_{preset_id}")
    
    builder.button(text="👁 Разрешение", callback_data=f"resolution_{preset_id}")
    builder.button(text="🔍 Grounding", callback_data=f"grounding_{preset_id}")
    
    builder.button(text="▶️ Запустить", callback_data=f"run_{preset_id}")
    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    
    builder.adjust(2, 2, 2, 1, 1)
    return builder.as_markup()


def get_multiturn_keyboard(preset_id: str):
    """Клавиатура для многоходового редактирования"""
    builder = InlineKeyboardBuilder()
    
    builder.button(text="🔄 Продолжить редактирование", callback_data=f"multiturn_{preset_id}")
    builder.button(text="💾 Сохранить это", callback_data=f"multiturn_save_{preset_id}")
    builder.button(text="📤 Скачать", callback_data=f"multiturn_download_{preset_id}")
    
    builder.button(text="🏠 В главное меню", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def get_prompt_tips_keyboard(preset_id: str):
    """Клавиатура с советами по промптам"""
    builder = InlineKeyboardBuilder()
    
    tips = [
        ("📸 Фотореализм", "tip_photo"),
        ("🎨 Иллюстрации", "tip_illustration"),
        ("🏭 Продакшн", "tip_product"),
        ("📝 Текст в изображении", "tip_text"),
    ]
    
    for tip_name, tip_callback in tips:
        builder.button(text=tip_name, callback_data=f"{tip_callback}_{preset_id}")
    
    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_batch_mode_keyboard():
    """Клавиатура выбора режима пакетной генерации"""
    builder = InlineKeyboardBuilder()
    
    builder.button(text="⚡ Standard (до 10)", callback_data="batch_mode_standard")
    builder.button(text="💎 Pro (до 5)", callback_data="batch_mode_pro")
    
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def get_preset_selection_keyboard(presets: list, mode: str):
    """Клавиатура выбора пресета для пакетной генерации"""
    builder = InlineKeyboardBuilder()
    
    base_cost = 3 if mode == "standard" else 15
    
    for preset in presets[:8]:
        builder.button(text=f"{preset.name} ({base_cost}🍌)", callback_data=f"batch_preset_{preset.id}")
    
    builder.button(text="✏️ Свои промпты", callback_data="batch_custom_prompts")
    builder.button(text="🔙 Назад", callback_data="batch_generation")
    
    builder.adjust(1, repeat=True)
    return builder.as_markup()


def get_confirmation_keyboard(yes_data: str, no_data: str, yes_text: str = "✅ Да", no_text: str = "❌ Нет"):
    """Универсальная клавиатура подтверждения"""
    builder = InlineKeyboardBuilder()
    
    builder.button(text=yes_text, callback_data=yes_data)
    builder.button(text=no_text, callback_data=no_data)
    
    builder.adjust(2)
    return builder.as_markup()


def get_batch_count_keyboard(preset_id: str, max_count: int):
    """Клавиатура выбора количества изображений для пакетной генерации"""
    builder = InlineKeyboardBuilder()
    
    counts = list(range(1, min(max_count + 1, 11)))
    
    for count in counts:
        builder.button(text=f"{count} 🖼", callback_data=f"batch_count_{preset_id}_{count}")
    
    builder.button(text="🔙 Назад", callback_data=f"batch_preset_{preset_id}")
    
    builder.adjust(5, repeat=True)
    return builder.as_markup()
