from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.services.preset_manager import preset_manager


def get_main_menu_keyboard(user_credits: int = 0):
    """Главное меню с опциональной кнопкой PRO"""
    builder = InlineKeyboardBuilder()

    builder.button(text="🖼 Генерация фото", callback_data="generate_image")
    builder.button(text="✏️ Редактировать фото", callback_data="edit_image")
    builder.button(text="🎬 Генерация видео", callback_data="generate_video")
    builder.button(text="🖼 Фото в видео", callback_data="image_to_video")
    builder.button(text="🎬 Motion Control", callback_data="menu_motion_control")
    builder.button(text="✂️ Видео-эффекты", callback_data="edit_video")

    # PRO-функция — пакетное редактирование (доступно при 20+ кредитах)
    if user_credits >= 20:
        builder.button(
            text="⚡ ПАКЕТНОЕ РЕДАКТИРОВАНИЕ", callback_data="menu_batch_edit"
        )

    builder.button(text="⚙️ Настройки", callback_data="menu_settings")
    builder.button(text="💳 Пополнить баланс", callback_data="menu_buy_credits")
    builder.button(text="📊 Мой баланс", callback_data="menu_balance")
    builder.button(text="❓ Помощь", callback_data="menu_help")

    if user_credits >= 20:
        builder.adjust(2, 2, 1, 2, 2, 1)
    else:
        builder.adjust(2, 2, 2, 1, 2, 1)
    return builder.as_markup()


def get_settings_keyboard(
    current_model: str = "flash",
    current_video_model: str = "v3_std",
    current_i2v_model: str = "v3_std",
    image_service: str = "novita",
):
    """
    Улучшенная клавиатура настроек - более понятная и информативная
    """
    builder = InlineKeyboardBuilder()

    # Получаем динамические цены
    try:
        flash_cost = preset_manager.get_generation_cost("gemini-2.5-flash")
        pro_cost = preset_manager.get_generation_cost("gemini-3-pro-image-preview")
        novita_cost = preset_manager.get_generation_cost("z_image_turbo")
        seedream_cost = preset_manager.get_generation_cost("seedream")
        
        # Цены видео за 5 сек
        v3_std_5 = preset_manager.get_video_cost("v3_std", 5)
        v3_pro_5 = preset_manager.get_video_cost("v3_pro", 5)
        omni_std_5 = preset_manager.get_video_cost("v3_omni_std", 5)
        omni_pro_5 = preset_manager.get_video_cost("v3_omni_pro", 5)
        
        # V2V цены за 5 сек
        r2v_std_5 = preset_manager.get_video_cost("v3_omni_std_r2v", 5)
        r2v_pro_5 = preset_manager.get_video_cost("v3_omni_pro_r2v", 5)
        
        # Kling 2.6 цены
        v26_5 = preset_manager.get_video_cost("v26_pro", 5)
        motion_pro_5 = preset_manager.get_video_cost("v26_motion_pro", 5)
        motion_std_5 = preset_manager.get_video_cost("v26_motion_std", 5)
    except Exception:
        # Значения по умолчанию если preset_manager не работает
        flash_cost = 3
        pro_cost = 5
        novita_cost = 3
        seedream_cost = 3
        v3_std_5 = 6
        v3_pro_5 = 8
        omni_std_5 = 8
        omni_pro_5 = 8
        r2v_std_5 = 8
        r2v_pro_5 = 8
        v26_5 = 8
        motion_pro_5 = 10
        motion_std_5 = 8

    # ═══════════════════════════════════════════════════════════════
    # 🖼 ИЗОБРАЖЕНИЯ
    # ═══════════════════════════════════════════════════════════════

    # Заголовок секции
    builder.button(text="📸 ━━━ ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ ━━━", callback_data="ignore")

    # Текущий выбор
    service_name = (
        "✨ FLUX.2 Pro"
        if image_service == "novita"
        else "🍌 Nano Banana"
        if image_service == "nanobanana"
        else "💎 Banana Pro"
        if image_service == "banana_pro"
        else "🎨 Seedream (Novita)"
        if image_service == "seedream"
        else "🚀 Z-Image Turbo LoRA"
        if image_service == "z_image_turbo"
        else "🎨 Seedream"
    )
    builder.button(text=f"✅ Текущий: {service_name}", callback_data="ignore")

    # Выбор сервиса - большие кнопки с описанием
    novita_active = "🟢 " if image_service == "novita" else "⚪ "
    nano_active = "🟢 " if image_service == "nanobanana" else "⚪ "
    banana_pro_active = "🟢 " if image_service == "banana_pro" else "⚪ "
    seedream_active = "🟢 " if image_service == "seedream" else "⚪ "
    turbo_lora_active = "🟢 " if image_service == "z_image_turbo" else "⚪ "

    builder.button(
        text=f"{novita_active}✨ FLUX.2 Pro (Novita)\n  До 1536px • Лучшее качество • {novita_cost}🍌",
        callback_data="settings_service_novita",
    )
    builder.button(
        text=f"{nano_active}🍌 Nano Banana\n  До 4K • Быстрая • {flash_cost}🍌",
        callback_data="settings_service_nanobanana",
    )
    builder.button(
        text=f"{banana_pro_active}💎 Banana Pro\n  Профи качество • 4K • {pro_cost}🍌",
        callback_data="settings_service_banana_pro",
    )
    builder.button(
        text=f"{seedream_active}🎨 Seedream\n  Стили • Арты • {seedream_cost}🍌",
        callback_data="settings_service_seedream",
    )
    builder.button(
        text=f"{turbo_lora_active}🚀 Z-Image Turbo LoRA\n  Быстрая • Свои LoRA • {novita_cost}🍌",
        callback_data="settings_service_z_image_turbo",
    )

    # Подсказка для FLUX
    if image_service == "novita":
        builder.button(
            text="ℹ️ FLUX.2 Pro: формат 1:1, 16:9, 9:16, до 1536px",
            callback_data="ignore",
        )

    # ═══════════════════════════════════════════════════════════════
    # 🎬 ВИДЕО: ТЕКСТ → ВИДЕО
    # ═══════════════════════════════════════════════════════════════

    builder.button(text="", callback_data="ignore")  # Отступ
    builder.button(text="🎬 ━━━ ТЕКСТ → ВИДЕО ━━━", callback_data="ignore")

    # Текущий выбор видео
    video_name = (
        "⚡ Std"
        if current_video_model == "v3_std"
        else "💎 Pro"
        if current_video_model == "v3_pro"
        else "🔄 Omni"
        if "omni" in current_video_model
        else "⚡ Std"
    )
    builder.button(text=f"✅ Текущий: {video_name}", callback_data="ignore")

    # Kling 3 Std/Pro
    v3_std = "🟢 " if current_video_model == "v3_std" else "⚪ "
    v3_pro = "🟢 " if current_video_model == "v3_pro" else "⚪ "

    builder.button(
        text=f"{v3_std}⚡ Kling 3 Standard\n  Быстро • {v3_std_5}🍌 за 5 сек",
        callback_data="settings_video_v3_std",
    )
    builder.button(
        text=f"{v3_pro}💎 Kling 3 Pro\n  Лучшее качество • {v3_pro_5}🍌 за 5 сек",
        callback_data="settings_video_v3_pro",
    )

    # Kling 3 Omni
    omni_std = "🟢 " if current_video_model == "v3_omni_std" else "⚪ "
    omni_pro = "🟢 " if current_video_model == "v3_omni_pro" else "⚪ "

    builder.button(
        text=f"{omni_std}🔄 Kling 3 Omni Std\n  Баланс • {omni_std_5}🍌",
        callback_data="settings_video_v3_omni_std",
    )
    builder.button(
        text=f"{omni_pro}💎 Kling 3 Omni Pro\n  Продвинутый • {omni_pro_5}🍌",
        callback_data="settings_video_v3_omni_pro",
    )

    # V2V (Video-to-Video)
    r2v_std = "🟢 " if current_video_model == "v3_omni_std_r2v" else "⚪ "
    r2v_pro = "🟢 " if current_video_model == "v3_omni_pro_r2v" else "⚪ "

    builder.button(
        text=f"{r2v_std}✂️ V2V Std (стилизация видео)\n  {r2v_std_5}🍌",
        callback_data="settings_video_v3_omni_std_r2v",
    )
    builder.button(
        text=f"{r2v_pro}💎 V2V Pro\n  {r2v_pro_5}🍌", callback_data="settings_video_v3_omni_pro_r2v"
    )

    # Kling 2.6 (нови!)
    v26_std = "🟢 " if current_video_model == "v26_pro" else "⚪ "
    
    builder.button(
        text=f"{v26_std}⚡ Kling 2.6 (Text → Video)\n  Самая быстрая • {v26_5}🍌 за 5 сек",
        callback_data="settings_video_v26_pro",
    )

    # ═══════════════════════════════════════════════════════════════
    # 📺 ФОТО → ВИДЕО
    # ═══════════════════════════════════════════════════════════════

    builder.button(text="", callback_data="ignore")  # Отступ
    builder.button(text="📺 ━━━ ФОТО → ВИДЕО ━━━", callback_data="ignore")

    # Текущий выбор
    i2v_name = (
        "⚡ Std"
        if current_i2v_model == "v3_std"
        else "💎 Pro"
        if current_i2v_model == "v3_pro"
        else "🔄 Omni"
        if "omni" in current_i2v_model
        else "⚡ Std"
    )
    builder.button(text=f"✅ Текущий: {i2v_name}", callback_data="ignore")

    # Image-to-Video модели
    i2v_std = "🟢 " if current_i2v_model == "v3_std" else "⚪ "
    i2v_pro = "🟢 " if current_i2v_model == "v3_pro" else "⚪ "
    i2v_omni_std = "🟢 " if current_i2v_model == "v3_omni_std" else "⚪ "
    i2v_omni_pro = "🟢 " if current_i2v_model == "v3_omni_pro" else "⚪ "

    builder.button(
        text=f"{i2v_std}⚡ Image-to-Video Std\n  Анимация фото • {v3_std_5}🍌",
        callback_data="settings_i2v_v3_std",
    )
    builder.button(
        text=f"{i2v_pro}💎 Image-to-Video Pro\n  Лучше качество • {v3_pro_5}🍌",
        callback_data="settings_i2v_v3_pro",
    )
    builder.button(
        text=f"{i2v_omni_std}🔄 Omni Std\n  Продвинутая • {omni_std_5}🍌",
        callback_data="settings_i2v_v3_omni_std",
    )
    builder.button(
        text=f"{i2v_omni_pro}💎 Omni Pro\n  Макс качество • {omni_pro_5}🍌",
        callback_data="settings_i2v_v3_omni_pro",
    )

    # ═══════════════════════════════════════════════════════════════
    # НАВИГАЦИЯ
    # ═══════════════════════════════════════════════════════════════

    builder.button(text="", callback_data="ignore")  # Отступ
    builder.button(text="🔙 Назад в главное меню", callback_data="back_main")
    builder.button(text="❓ Помощь по настройкам", callback_data="menu_help")

    # Компоновка - адаптивная
    builder.adjust(
        1,  # Заголовок изображений
        1,  # Текущий выбор
        1,
        1,
        1,
        1,  # 4 сервиса (FLUX, Nano, Banana Pro, Seedream)
        1,  # Подсказка FLUX
        1,  # Отступ
        1,  # Заголовок видео
        1,  # Текущий выбор видео
        1,
        1,  # Kling 3
        1,
        1,  # Omni
        1,
        1,  # V2V
        1,  # Отступ
        1,  # Заголовок i2v
        1,  # Текущий выбор i2v
        1,
        1,
        1,
        1,  # i2v модели
        1,  # Отступ
        2,  # Навигация
    )
    return builder.as_markup()


def get_category_keyboard(category: str, presets: list, user_credits: int):
    """Клавиатура выбора пресета в категории"""
    builder = InlineKeyboardBuilder()

    for preset in presets:
        affordable = "✅" if user_credits >= preset.cost else "❌"
        # Показываем описание для видео пресетов
        if hasattr(preset, "description") and preset.description:
            display_text = f"{preset.name}\n   📝 {preset.description[:40]}..."
        else:
            display_text = preset.name
        builder.button(
            text=f"{display_text} — {preset.cost}🍌 {affordable}",
            callback_data=f"preset_{preset.id}",
        )

    builder.button(text="🔙 Назад в меню", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def get_preset_action_keyboard(preset_id: str, has_input: bool, category: str = None):
    """Действия с выбранным пресетом"""
    builder = InlineKeyboardBuilder()

    # Для видео показываем кнопки опций
    if category in ["video_generation", "video_editing"]:
        builder.button(text="⏱ Длительность", callback_data=f"opt_duration_{preset_id}")
        builder.button(text="📐 Формат", callback_data=f"opt_ratio_{preset_id}")

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


def get_duration_keyboard(preset_id: str, current_duration: int = 5):
    """Клавиатура выбора длительности видео"""
    builder = InlineKeyboardBuilder()

    durations = [3, 5, 10, 15]

    for dur in durations:
        emoji = "✅" if dur == current_duration else ""
        builder.button(
            text=f"{dur} сек {emoji}", callback_data=f"duration_{preset_id}_{dur}"
        )

    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    builder.adjust(2)
    return builder.as_markup()


def get_aspect_ratio_keyboard(preset_id: str, current_ratio: str = "16:9"):
    """Клавиатура выбора формата видео"""
    builder = InlineKeyboardBuilder()

    ratios = {
        "16:9": "📺 Landscape (YouTube)",
        "9:16": "📱 Vertical (TikTok/Reels)",
        "1:1": "⬜ Square (Instagram)",
    }

    for ratio, label in ratios.items():
        emoji = "✅" if ratio == current_ratio else ""
        builder.button(
            text=f"{label} {emoji}", callback_data=f"ratio_{preset_id}_{ratio}"
        )

    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    builder.adjust(1)
    return builder.as_markup()


def get_image_aspect_ratio_no_preset_keyboard(current_ratio: str = "1:1"):
    """
    Клавиатура выбора формата изображения для генерации без пресета.
    """
    builder = InlineKeyboardBuilder()

    ratios = [
        ("1:1", "⬜ 1:1", "Квадрат"),
        ("16:9", "📺 16:9", "Горизонтальный"),
        ("9:16", "📱 9:16", "Вертикальный"),
        ("4:5", "📸 4:5", "Портретный"),
        ("21:9", "🎬 21:9", "Панорамный"),
    ]

    for ratio, emoji, label in ratios:
        check = "✅" if ratio == current_ratio else ""
        ratio_callback = ratio.replace(":", "_")
        builder.button(
            text=f"{emoji} {label} {check}",
            callback_data=f"img_ratio_no_preset_{ratio_callback}",
        )

    builder.button(text="▶️ Запустить", callback_data="run_no_preset_image")
    builder.button(text="🔙 Назад", callback_data="back_main")

    builder.adjust(2, 2, 1, 2)
    return builder.as_markup()


def get_image_aspect_ratio_no_preset_edit_keyboard(current_ratio: str = "1:1"):
    """
    Клавиатура выбора формата изображения для редактирования без пресета.
    """
    builder = InlineKeyboardBuilder()

    ratios = [
        ("1:1", "⬜ 1:1", "Квадрат"),
        ("16:9", "📺 16:9", "Горизонтальный"),
        ("9:16", "📱 9:16", "Вертикальный"),
        ("4:5", "📸 4:5", "Портретный"),
        ("21:9", "🎬 21:9", "Панорамный"),
    ]

    for ratio, emoji, label in ratios:
        check = "✅" if ratio == current_ratio else ""
        ratio_callback = ratio.replace(":", "_")
        builder.button(
            text=f"{emoji} {label} {check}",
            callback_data=f"img_ratio_no_preset_edit_{ratio_callback}",
        )

    builder.button(text="▶️ Запустить", callback_data="run_no_preset_edit_image")
    builder.button(text="🔙 Назад", callback_data="back_main")

    builder.adjust(2, 2, 1, 2)
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


def get_video_options_no_preset_keyboard(
    current_duration: int = 5, current_ratio: str = "16:9", current_audio: bool = True
):
    """Клавиатура опций видео без пресета"""
    builder = InlineKeyboardBuilder()

    builder.button(text="⚙️ Настройки видео:", callback_data="video_settings_header")

    durations = [3, 5, 10, 15]
    for dur in durations:
        emoji = "✅" if dur == current_duration else ""
        builder.button(
            text=f"⏱ {dur}с {emoji}", callback_data=f"no_preset_duration_{dur}"
        )

    ratios = [
        ("16:9", "📺 16:9"),
        ("9:16", "📱 9:16"),
        ("1:1", "⬜ 1:1"),
    ]
    for ratio, label in ratios:
        emoji = "✅" if ratio == current_ratio else ""
        ratio_callback = ratio.replace(":", "_")
        builder.button(
            text=f"{label} {emoji}", callback_data=f"no_preset_ratio_{ratio_callback}"
        )

    audio_on = "✅" if current_audio else ""
    audio_off = "✅" if not current_audio else ""
    builder.button(text=f"🔊 Со звуком {audio_on}", callback_data="no_preset_audio_on")
    builder.button(text=f"🔇 Без звука {audio_off}", callback_data="no_preset_audio_off")

    builder.button(text="▶️ Запустить", callback_data="run_no_preset_video")
    builder.button(text="🔙 Назад", callback_data="back_main")

    builder.adjust(1, 3, 3, 2, 1, 2)
    return builder.as_markup()


def get_quality_keyboard(preset_id: str):
    """Клавиатура выбора качества видео"""
    builder = InlineKeyboardBuilder()

    builder.button(
        text="⚡ Standard (быстрее, дешевле)", callback_data=f"quality_{preset_id}_std"
    )
    builder.button(
        text="💎 Pro (лучшее качество)", callback_data=f"quality_{preset_id}_pro"
    )

    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    builder.adjust(1)
    return builder.as_markup()


# =============================================================================
# НОВЫЕ КЛАВИАТУРЫ ДЛЯ NANOBANANA API
# =============================================================================


def get_model_selection_keyboard(preset_id: str, current_model: str = None):
    """Клавиатура выбора модели генерации"""
    builder = InlineKeyboardBuilder()

    flash_selected = "✅" if current_model and "flash" in current_model else ""
    builder.button(
        text=f"⚡ Nano Banana Flash {flash_selected}\n   Быстрая, до 1024px",
        callback_data=f"model_{preset_id}_flash",
    )

    pro_selected = "✅" if current_model and "pro" in current_model else ""
    builder.button(
        text=f"💎 Nano Banana Pro {pro_selected}\n   До 4K, с reasoning",
        callback_data=f"model_{preset_id}_pro",
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
        ("4K", "👑 Ultra (4096px)", "4K"),
    ]

    for res, label, _ in resolutions:
        emoji = "✅" if res == current_resolution else ""
        builder.button(
            text=f"{label} {emoji}", callback_data=f"resolution_{preset_id}_{res}"
        )

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
        ("21:9", "🎬 Панорамный"),
    ]

    for ratio, label in ratios:
        emoji = "✅" if ratio == current_ratio else ""
        builder.button(
            text=f"{label} ({ratio}) {emoji}",
            callback_data=f"img_ratio_{preset_id}_{ratio}",
        )

    builder.button(text="🔙 Назад", callback_data=f"model_{preset_id}")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_reference_images_keyboard(preset_id: str):
    """Клавиатура для работы с референсными изображениями"""
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🖼 Добавить референс (до 14)", callback_data=f"ref_add_{preset_id}"
    )
    builder.button(
        text="👤 Добавить референс человека", callback_data=f"ref_person_{preset_id}"
    )
    builder.button(text="📦 Показать загруженные", callback_data=f"ref_list_{preset_id}")
    builder.button(text="🗑 Очистить все", callback_data=f"ref_clear_{preset_id}")

    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    builder.adjust(1, 1, 2, 1)
    return builder.as_markup()


def get_search_grounding_keyboard(preset_id: str, enabled: bool = False):
    """Клавиатура для поискового заземления (Grounding)"""
    builder = InlineKeyboardBuilder()

    status = "🔴 ВЫКЛ" if enabled else "🟢 ВКЛ"
    builder.button(
        text=f"🔍 Поиск в интернете: {status}",
        callback_data=f"grounding_{preset_id}_toggle",
    )

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

    builder.button(
        text="🔄 Продолжить редактирование", callback_data=f"multiturn_{preset_id}"
    )
    builder.button(text="💾 Сохранить это", callback_data=f"multiturn_save_{preset_id}")
    builder.button(text="📤 Скачать", callback_data=f"multiturn_download_{preset_id}")

    builder.button(text="🏠 В главное меню", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def get_video_edit_input_type_keyboard():
    """Клавиатура выбора типа входных данных для видео-эффектов"""
    builder = InlineKeyboardBuilder()

    builder.button(text="🎬 Загрузить видео", callback_data="video_edit_input_video")
    builder.button(text="🖼 Загрузить фото", callback_data="video_edit_input_image")

    builder.button(text="🔙 Назад", callback_data="back_main")

    builder.adjust(1, 1)
    return builder.as_markup()


def get_video_edit_keyboard(
    preset_id: str = None,
    input_type: str = "video",
    quality: str = "std",
    duration: int = 5,
    aspect_ratio: str = "16:9",
):
    """Клавиатура для видео-эффектов"""
    builder = InlineKeyboardBuilder()

    std_check = "✅ " if quality == "std" else ""
    pro_check = "✅ " if quality == "pro" else ""

    builder.button(
        text=f"{std_check}⚡ Standard", callback_data=f"video_edit_quality_std"
    )
    builder.button(text=f"{pro_check}💎 Pro", callback_data=f"video_edit_quality_pro")

    dur5_check = "✅ " if duration == 5 else ""
    dur10_check = "✅ " if duration == 10 else ""
    dur15_check = "✅ " if duration == 15 else ""

    builder.button(text=f"{dur5_check}⏱ 5 сек", callback_data=f"video_edit_duration_5")
    builder.button(
        text=f"{dur10_check}⏱ 10 сек", callback_data=f"video_edit_duration_10"
    )
    builder.button(
        text=f"{dur15_check}⏱ 15 сек", callback_data=f"video_edit_duration_15"
    )

    ratio_9_16_check = "✅ " if aspect_ratio == "9:16" else ""
    ratio_16_9_check = "✅ " if aspect_ratio == "16:9" else ""
    ratio_1_1_check = "✅ " if aspect_ratio == "1:1" else ""

    builder.button(
        text=f"{ratio_9_16_check}📱 9:16 (TikTok)",
        callback_data=f"video_edit_ratio_9_16",
    )
    builder.button(
        text=f"{ratio_16_9_check}📺 16:9 (YouTube)",
        callback_data=f"video_edit_ratio_16_9",
    )
    builder.button(
        text=f"{ratio_1_1_check}⬜ 1:1 (Square)", callback_data=f"video_edit_ratio_1_1"
    )

    if input_type == "image":
        builder.button(text="▶️ Запустить", callback_data="run_video_edit_image")
    else:
        builder.button(text="▶️ Запустить", callback_data="run_video_edit")

    builder.button(text="🔄 Сменить тип", callback_data="video_edit_change_type")
    builder.button(text="🔙 Назад", callback_data="back_main")

    builder.adjust(2, 2, 3, 1, 1, 1)
    return builder.as_markup()


def get_video_edit_confirm_keyboard():
    """Клавиатура подтверждения для видео-эффектов"""
    builder = InlineKeyboardBuilder()

    builder.button(text="▶️ Запустить", callback_data="run_video_edit")
    builder.button(text="🔙 Назад", callback_data="edit_video")

    builder.adjust(2)
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


# =============================================================================
# КЛАВИАТУРЫ ДЛЯ ПАКЕТНОЙ ГЕНЕРАЦИИ
# =============================================================================


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
        builder.button(
            text=f"{preset.name} ({base_cost}🍌)",
            callback_data=f"batch_preset_{preset.id}",
        )

    builder.button(text="✏️ Свои промпты", callback_data="batch_custom_prompts")
    builder.button(text="🔙 Назад", callback_data="batch_generation")

    builder.adjust(1, repeat=True)
    return builder.as_markup()


def get_confirmation_keyboard(
    yes_data: str, no_data: str, yes_text: str = "✅ Да", no_text: str = "❌ Нет"
):
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
        builder.button(
            text=f"{count} 🖼", callback_data=f"batch_count_{preset_id}_{count}"
        )

    builder.button(text="🔙 Назад", callback_data=f"batch_preset_{preset_id}")

    builder.adjust(5, repeat=True)
    return builder.as_markup()


def get_video_result_keyboard(video_url: str, user_credits: int = 0):
    """Клавиатура для готового видео"""
    builder = InlineKeyboardBuilder()

    builder.button(text="📥 Скачать видео", url=video_url)
    builder.button(text="🏠 Главное меню", callback_data="back_main")

    builder.adjust(1)
    return builder.as_markup()


def get_ai_assistant_keyboard():
    """Клавиатура для ИИ-ассистента"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 В главное меню", callback_data="back_main")
    return builder.as_markup()


def get_motion_control_keyboard():
    """Клавиатура выбора качества Motion Control"""
    builder = InlineKeyboardBuilder()
    
    builder.button(
        text="⚡ Motion Control Standard\n  8🍌 за 5 сек • Быстрее",
        callback_data="motion_control_std",
    )
    builder.button(
        text="💎 Motion Control Pro\n  10🍌 за 5 сек • Лучше качество",
        callback_data="motion_control_pro",
    )
    
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


# =============================================================================
# УЛУЧШЕННЫЕ ФУНКЦИИ (для обратной совместимости)
# =============================================================================


def get_settings_main_keyboard(
    current_image_service: str = "novita",
    current_video_model: str = "v3_std",
):
    """Главное меню настроек - упрощённый UX"""
    return get_settings_keyboard(
        current_model="flash",
        current_video_model=current_video_model,
        current_i2v_model="v3_std",
        image_service=current_image_service,
    )


def get_settings_images_keyboard(
    current_service: str = "novita",
    current_model: str = "flux_pro",
):
    """Настройки генерации изображений"""
    return get_settings_keyboard(
        current_model=current_model,
        current_video_model="v3_std",
        current_i2v_model="v3_std",
        image_service=current_service,
    )


def get_settings_video_keyboard(
    current_model: str = "v3_std",
):
    """Настройки генерации видео"""
    return get_settings_keyboard(
        current_model="flash",
        current_video_model=current_model,
        current_i2v_model="v3_std",
        image_service="novita",
    )


def get_settings_i2v_keyboard(
    current_model: str = "v3_std",
):
    """Настройки фото в видео"""
    return get_settings_keyboard(
        current_model="flash",
        current_video_model="v3_std",
        current_i2v_model=current_model,
        image_service="novita",
    )


def get_settings_keyboard_with_ali(
    current_model: str = "flash",
    current_video_model: str = "v3_std",
    current_i2v_model: str = "v3_std",
    image_service: str = "novita",
):
    """Клавиатура настроек (алиас для совместимости)"""
    return get_settings_keyboard(
        current_model=current_model,
        current_video_model=current_video_model,
        current_i2v_model=current_i2v_model,
        image_service=image_service,
    )


def get_settings_keyboard_with_ai(
    current_model: str = "flash",
    current_video_model: str = "v3_std",
    current_i2v_model: str = "v3_std",
    image_service: str = "novita",
):
    """Клавиатура настроек (для совместимости)"""
    return get_settings_keyboard(
        current_model=current_model,
        current_video_model=current_video_model,
        current_i2v_model=current_i2v_model,
        image_service=image_service,
    )
