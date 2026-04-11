import json
import os

from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


# Загрузка цен из price.json
def load_prices():
    """Загружает цены из price.json"""
    price_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "price.json"
    )
    try:
        with open(price_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Значения по умолчанию если файл не найден
        return {
            "costs_reference": {
                "image_models": {
                    "flux_pro": 3,
                    "nanobanana": 3,
                    "banana_pro": 5,
                    "seedream": 3,
                },
                "video_models": {
                    "v26_pro": {"base": 8, "duration_costs": {"5": 8, "10": 14}},
                    "v3_std": {
                        "base": 6,
                        "duration_costs": {"5": 6, "10": 8, "15": 10},
                    },
                    "v3_pro": {
                        "base": 8,
                        "duration_costs": {"5": 8, "10": 14, "15": 16},
                    },
                    "v3_omni_std": {
                        "base": 8,
                        "duration_costs": {"5": 8, "10": 14, "15": 16},
                    },
                    "v3_omni_pro": {
                        "base": 8,
                        "duration_costs": {"5": 8, "10": 14, "15": 16},
                    },
                },
            },
            "packages": [
                {"id": "mini", "credits": 15, "price_rub": 150},
                {"id": "standard", "credits": 30, "price_rub": 250},
                {"id": "optimal", "credits": 50, "price_rub": 400, "popular": True},
                {"id": "pro", "credits": 100, "price_rub": 700},
            ],
        }


PRICES = load_prices()

# Словари для удобного доступа
IMAGE_COSTS = PRICES.get("costs_reference", {}).get(
    "image_models",
    {
        "nanobanana": 3,
        "banana_pro": 5,
        "banana_2": 7,
    },
)


VIDEO_COSTS = PRICES.get("costs_reference", {}).get(
    "video_models",
    {
        "v3_std": {"base": 6, "duration_costs": {"5": 6, "10": 8, "15": 10}},
        "v3_pro": {"base": 8, "duration_costs": {"5": 8, "10": 14, "15": 16}},
        "v3_omni_std": {"base": 8, "duration_costs": {"5": 8, "10": 14, "15": 16}},
        "v3_omni_pro": {"base": 8, "duration_costs": {"5": 8, "10": 14, "15": 16}},
        "v26_pro": {"base": 8, "duration_costs": {"5": 8, "10": 14}},
        "v26_motion_pro": {"base": 10, "duration_costs": {"5": 10, "10": 18}},
        "v26_motion_std": {"base": 8, "duration_costs": {"5": 8, "10": 14}},
        "z_image_turbo_lora": {"base": 3, "duration_costs": {"5": 3, "10": 6, "15": 9}},
        "grok_imagine": {"base": 15, "duration_costs": {"6": 15, "20": 40, "30": 60}},
    },
)

PACKAGES = PRICES.get("packages", [])


# =============================================================================
# ГЛАВНОЕ МЕНЮ - согласно ux.md
# =============================================================================


def get_main_menu_keyboard(user_credits: int = 0):
    """Главное меню бота - согласно ux.md"""
    builder = InlineKeyboardBuilder()

    builder.button(text="🎬 Создать видео", callback_data="create_video_new")
    builder.button(text="🖼 Создать фото", callback_data="create_image_refs_new")
    builder.button(text="🎯 Motion Control", callback_data="motion_control")

    builder.button(text="📸 Фото=Промпт", callback_data="photo_to_prompt")
    builder.button(text="💼 Партнёрам", callback_data="menu_partner")
    builder.button(text="💰 Пополнить", callback_data="menu_topup")
    builder.button(text="🆘 Тех. поддержка", callback_data="menu_support")
    builder.button(text="❓ Помощь бота", callback_data="menu_help")

    builder.adjust(2, 2, 2, 2)

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


# =============================================================================
# МЕНЮ СОЗДАНИЯ ВИДЕО - всё на одном экране
# =============================================================================


def get_create_video_keyboard(
    current_v_type: str = "text",
    current_model: str = "v3_std",
    current_ratio: str = "16:9",
    current_duration: int = 5,
    current_mode: str = "720p",
    current_orientation: str = "video",
    current_video_model: str = None,  # Алиас для обратной совместимости
    current_grok_mode: str = "normal",
    current_grok_res: str = "720p",  # Default to max quality
    current_grok_nsfw: bool = False,
):
    """Меню создания видео - всё на одном экране"""
    # Если передан current_video_model, используем его
    if current_video_model is not None:
        current_model = current_video_model

    builder = InlineKeyboardBuilder()

    # Тип генерации - текст, фото+текст или видео+текст
    text_check = "✅ " if current_v_type == "text" else ""
    imgtxt_check = "✅ " if current_v_type == "imgtxt" else ""
    video_check = "✅ " if current_v_type == "video" else ""

    builder.button(text=f"{text_check}📝 Текст → Видео", callback_data="v_type_text")
    builder.button(
        text=f"{imgtxt_check}🖼 Фото + Текст → Видео", callback_data="v_type_imgtxt"
    )
    builder.button(
        text=f"{video_check}🎬 Видео + Текст → Видео (Motion Control)",
        callback_data="v_type_video",
    )

    # Модели - из price.json
    v26_data = VIDEO_COSTS.get("v26_pro", {"base": 8, "duration_costs": {"5": 8}})
    v3_std_data = VIDEO_COSTS.get("v3_std", {"base": 6, "duration_costs": {"5": 6}})
    v3_pro_data = VIDEO_COSTS.get("v3_pro", {"base": 8, "duration_costs": {"5": 8}})
    omni_data = VIDEO_COSTS.get("v3_omni_std", {"base": 8, "duration_costs": {"5": 8}})
    v3_omni_pro_data = VIDEO_COSTS.get(
        "v3_omni_pro", {"base": 8, "duration_costs": {"5": 8, "10": 14, "15": 16}}
    )
    v26_motion_data = VIDEO_COSTS.get(
        "v26_motion_pro", {"base": 10, "duration_costs": {"5": 10}}
    )

    grok_data = VIDEO_COSTS.get("grok_imagine", {"base": 15, "duration_costs": {"6": 15}})
    grok_cost = grok_data.get("duration_costs", {}).get(str(current_duration), grok_data.get("base", 15))

    v26_cost = v26_data.get("duration_costs", {}).get(
        str(current_duration), v26_data.get("base", 8)
    )
    v3_std_cost = v3_std_data.get("duration_costs", {}).get(
        str(current_duration), v3_std_data.get("base", 6)
    )
    v3_pro_cost = v3_pro_data.get("duration_costs", {}).get(
        str(current_duration), v3_pro_data.get("base", 8)
    )
    omni_cost = omni_data.get("duration_costs", {}).get(
        str(current_duration), omni_data.get("base", 8)
    )
    v26_motion_cost = v26_motion_data.get("duration_costs", {}).get(
        str(current_duration), v26_motion_data.get("base", 10)
    )

    v3_omni_std_cost = omni_data.get("duration_costs", {}).get(
        str(current_duration), omni_data.get("base", 8)
    )
    v3_omni_pro_cost = v3_omni_pro_data.get("duration_costs", {}).get(
        str(current_duration), v3_omni_pro_data.get("base", 8)
    )

    seedance_data = VIDEO_COSTS.get("seedance2", {"duration_costs": {"5": 8}})
    seedance_cost = seedance_data.get("duration_costs", {}).get(str(current_duration), 8)

    runway_data = VIDEO_COSTS.get("runway", {"base": 15, "duration_costs": {"5": 15, "10": 25}})
    runway_cost = runway_data.get("duration_costs", {}).get(str(current_duration), runway_data.get("base", 15))


    if current_v_type == "video":
        models = []

    else:
        models = [
            {"key": "v3_std", "label": "⚡ Kling 3 Std", "cost": v3_std_cost},
            {"key": "v3_pro", "label": "💎 Kling 3 Pro", "cost": v3_pro_cost},
            {
                "key": "seedance2",
                "label": "🌱 Seedance 2.0",
                "cost": seedance_cost,
            },
            {
                "key": "runway",
                "label": "🎥 Runway AI",
                "cost": runway_cost,
            },
            {
                "key": "grok_imagine",
                "label": "🧠 Grok Imagine",
                "cost": grok_cost,
            },
        ]


    for model_info in models:
        check = "✅ " if current_model == model_info["key"] else ""
        builder.button(
            text=f"{check}{model_info['label']} • {model_info['cost']}🍌",
            callback_data=f"v_model_{model_info['key']}",
        )

    # Размер - все доступные форматы
    r1_1 = "✅ " if current_ratio == "1:1" else ""
    r16_9 = "✅ " if current_ratio == "16:9" else ""
    r9_16 = "✅ " if current_ratio == "9:16" else ""
    r4_3 = "✅ " if current_ratio == "4:3" else ""
    r3_2 = "✅ " if current_ratio == "3:2" else ""

    builder.button(text=f"{r1_1}1:1", callback_data="ratio_1_1")
    builder.button(text=f"{r16_9}16:9", callback_data="ratio_16_9")
    builder.button(text=f"{r9_16}9:16", callback_data="ratio_9_16")
    builder.button(text=f"{r4_3}4:3", callback_data="ratio_4_3")
    builder.button(text=f"{r3_2}3:2", callback_data="ratio_3_2")

    # Длительности: показываем только поддерживаемые моделью значения
    model_data_for_durations = VIDEO_COSTS.get(current_model, {})
    duration_costs = model_data_for_durations.get("duration_costs", {})
    if duration_costs:
        # Используем отсортированный список доступных длительностей из конфигурации
        available_durations = sorted([int(k) for k in duration_costs.keys()])
    else:
        # По умолчанию показываем 5/10/15
        available_durations = [5, 10, 15]

    for dur in available_durations:
        check = "✅ " if current_duration == dur else ""
        builder.button(text=f"{check}{dur} сек", callback_data=f"video_dur_{dur}")

    if current_v_type == "video":
        # Motion Control options
        mode_check_720p = "✅ " if current_mode == "720p" else ""
        mode_check_1080p = "✅ " if current_mode == "1080p" else ""
        orient_check_image = "✅ " if current_orientation == "image" else ""
        orient_check_video = "✅ " if current_orientation == "video" else ""

        builder.button(
            text=f"{mode_check_720p}📱 720p (std)", callback_data="v_mode_720p"
        )
        builder.button(
            text=f"{mode_check_1080p}🖥 1080p (pro)", callback_data="v_mode_1080p"
        )
        builder.button(
            text=f"{orient_check_image}🖼 Image orient",
            callback_data="v_orientation_image",
        )
        builder.button(
            text=f"{orient_check_video}🎬 Video orient",
            callback_data="v_orientation_video",
        )

    # Рассчитываем цену
    model_data = VIDEO_COSTS.get(current_model, {"base": 6, "duration_costs": {"5": 6}})
    total_cost = model_data.get("duration_costs", {}).get(
        str(current_duration), model_data.get("base", 6)
    )

    # Кнопка создания - после выбора опций пользователь отправляет промпт
    builder.button(text=f"💰 {total_cost}🍌", callback_data="back_main")
    builder.button(text="🏠 Главное меню", callback_data="back_main")

    num_models = len(models)
    widths = [3] + [1] * num_models + [5, len(available_durations), 2]
    if current_v_type == "video":
        widths += [4, 2]
    builder.adjust(*widths)
    return builder.as_markup()


# =============================================================================
# МЕНЮ СОЗДАНИЯ ФОТО - всё на одном экране
# =============================================================================


def get_create_image_keyboard(
    current_service: str = "banana_pro", current_ratio: str = "1:1", num_refs: int = 0
):
    """Меню создания фото - всё на одном экране"""
    builder = InlineKeyboardBuilder()

    # Модели - Kei.ai only
    pro_cost = IMAGE_COSTS.get("banana_pro", 5)
    banana2_cost = IMAGE_COSTS.get("banana_2", 7)
    seedream_5_lite_cost = IMAGE_COSTS.get("seedream_5_lite", 6)
    seedream_edit_cost = IMAGE_COSTS.get("seedream_edit", 7)

    pro_check = "✅ " if current_service == "banana_pro" else ""
    banana2_check = "✅ " if current_service == "banana_2" else ""
    seedream_5_lite_check = "✅ " if current_service == "seedream_5_lite" else ""
    seedream_edit_check = "✅ " if current_service == "seedream_edit" else ""

    # Models - each on new line (vertical list)
    builder.button(
        text=f"{pro_check}💎 Banana Pro • {pro_cost}🍌",
        callback_data="model_banana_pro",
    )
    builder.button(
        text=f"{banana2_check}🍌 Banana 2 • {banana2_cost}🍌",
        callback_data="model_banana_2",
    )
    builder.button(
        text=f"{seedream_5_lite_check}🔥 Seedream 5.0 Lite • {seedream_5_lite_cost}🍌",
        callback_data="model_seedream_5_lite",
    )
    if num_refs > 0:
        builder.button(
            text=f"{seedream_edit_check}🖌 Seedream 4.5 • {seedream_edit_cost}🍌",
            callback_data="model_seedream_edit",
        )

    # Размер - под моделями (two rows)
    r1_1 = "✅ " if current_ratio == "1:1" else ""
    r16_9 = "✅ " if current_ratio == "16:9" else ""
    r9_16 = "✅ " if current_ratio == "9:16" else ""
    r4_3 = "✅ " if current_ratio == "4:3" else ""
    r3_2 = "✅ " if current_ratio == "3:2" else ""

    builder.row(
        InlineKeyboardButton(text=f"{r1_1}1:1", callback_data="img_ratio_1_1"),
        InlineKeyboardButton(text=f"{r16_9}16:9", callback_data="img_ratio_16_9"),
        InlineKeyboardButton(text=f"{r9_16}9:16", callback_data="img_ratio_9_16"),
    )
    builder.row(
        InlineKeyboardButton(text=f"{r4_3}4:3", callback_data="img_ratio_4_3"),
        InlineKeyboardButton(text=f"{r3_2}3:2", callback_data="img_ratio_3_2"),
    )

    # Main menu button
    builder.button(text="🏠 Главное меню", callback_data="back_main")

    # Adjust: 4 model buttons (1 each), aspect row1 (3), row2 (2), menu (1)
    # If no edit model: 3 models + aspects + menu
    builder.adjust(1, 1, 1, 1, 3, 2, 1)

    return builder.as_markup()



# =============================================================================
# МЕНЮ ПОПОЛНЕНИЯ
# =============================================================================


def get_topup_keyboard():
    """Меню пополнения баланса"""
    from bot.config import config

    return get_payment_packages_keyboard(PACKAGES, provider=config.payment_provider)


def get_payment_provider_keyboard(current_provider: str = "tbank"):
    """Выбор платёжного провайдера"""
    builder = InlineKeyboardBuilder()

    tbank_check = "✅ " if current_provider == "tbank" else ""
    yk_check = "✅ " if current_provider == "yookassa" else ""

    builder.button(
        text=f"{tbank_check}💳 Т-Банк",
        callback_data="topup_provider_tbank",
    )
    builder.button(
        text=f"{yk_check}💜 YooKassa",
        callback_data="topup_provider_yookassa",
    )
    builder.adjust(2)
    return builder.as_markup()


def get_payment_packages_keyboard(packages: list, provider: str = None):
    """Клавиатура выбора пакета бананов с выбором провайдера"""
    from bot.config import config

    provider = provider or config.payment_provider
    if provider not in {"tbank", "yookassa"}:
        provider = "tbank"

    builder = InlineKeyboardBuilder()
    provider_kb = get_payment_provider_keyboard(provider)
    if provider_kb.inline_keyboard:
        builder.row(*provider_kb.inline_keyboard[0])

    for pkg in packages:
        popular = " 🔥" if pkg.get("popular") else ""
        builder.button(
            text=f"{pkg['name']}: {pkg['credits']}🍌 за {pkg['price_rub']}₽{popular}",
            callback_data=f"buy_{provider}_{pkg['id']}",
        )

    builder.adjust(2, 1)
    return builder.as_markup()


# =============================================================================
# МЕНЮ БАЛАНСА
# =============================================================================


def get_balance_keyboard(user_credits: int = 0):
    """Меню баланса"""
    builder = InlineKeyboardBuilder()

    builder.button(text=f"У тебя: {user_credits} 🍌", callback_data="back_main")

    builder.button(text="💰 Пополнить", callback_data="menu_topup")
    builder.button(text="📋 История", callback_data="menu_history")

    builder.adjust(1, 2)
    return builder.as_markup()


# =============================================================================
# ТЕХ. ПОДДЕРЖКА И ПОМОЩЬ
# =============================================================================


def get_support_keyboard():
    """Клавиатура тех. поддержки"""
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 ИИ-ассистент", callback_data="menu_ai_assistant")
    builder.button(text="🔙 Главное меню", callback_data="back_main")
    builder.adjust(1, 1)
    return builder.as_markup()


def get_help_keyboard():
    """Клавиатура помощи"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Главное меню", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


# =============================================================================
# АЛИАСЫ ДЛЯ ОБРАТНОЙ СОВМЕСТИМОСТИ
# =============================================================================


def get_create_menu_keyboard():
    """Алиас для обратной совместимости"""
    return get_create_video_keyboard()


def get_payment_confirmation_keyboard(payment_url: str, order_id: str):
    """Клавиатура подтверждения оплаты"""
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Перейти к оплате", url=payment_url)
    builder.button(text="🔙 Назад", callback_data="menu_topup")
    builder.adjust(1)
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


def get_referral_keyboard(referral_link: str):
    """Клавиатура реферальной системы."""
    builder = InlineKeyboardBuilder()
    share_url = f"https://t.me/share/url?url={referral_link}"
    builder.button(text="📨 Поделиться", url=share_url)
    builder.button(text="🔄 Обновить", callback_data="menu_referrals")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def get_partner_program_keyboard(referral_link: str, is_partner: bool = False):
    """Клавиатура партнёрской программы."""
    builder = InlineKeyboardBuilder()
    # Всегда предоставляем кнопку для просмотра публичной оферты
    builder.button(text="📜 Публичная оферта", callback_data="partner_offer")
    if not is_partner:
        builder.button(
            text="✔ Прочитал и согласен с условиями", callback_data="partner_accept"
        )
    if referral_link:
        share_url = f"https://t.me/share/url?url={referral_link}"
        builder.button(text="📨 Поделиться ссылкой", url=share_url)
    builder.button(text="📈 Детальная статистика", callback_data="partner_stats")
    builder.button(text="🔄 Обновить", callback_data="menu_partner")
    builder.button(text="🎟️ Вывод заработка", callback_data="partner_withdraw")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1, 1, 1, 1)
    return builder.as_markup()


def get_partner_consent_keyboard():
    """Клавиатура подтверждения участия в партнёрской программе."""
    from bot.config import config

    builder = InlineKeyboardBuilder()
    # If an external URL is configured, open it in browser; otherwise use an internal
    # callback which will load the local static/ofert.md file and show it in-chat.
    # Всегда показываем оферту через внутренний callback — чтобы оферта была
    # доступна пользователю независимо от внешних настроек/хостинга.
    builder.button(text="📜 Публичная оферта", callback_data="partner_offer")

    # Правила могут вести на внешний URL, если он настроен; иначе используем
    # внешний заглушечный URL (для правил внутреннего файла нет).
    rules_url = config.PARTNER_RULES_URL
    if rules_url:
        builder.button(text="📘 Правила", url=rules_url)
    else:
        builder.button(text="📘 Правила", url="https://example.com/rules")
    builder.button(
        text="✔ Прочитал и согласен с условиями", callback_data="partner_accept"
    )
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


# =============================================================================
# ДОПОЛНИТЕЛЬНЫЕ ФУНКЦИИ (для совместимости)
# =============================================================================


def get_upload_menu_keyboard():
    """Меню загрузки медиа"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🖼 Загрузить фото", callback_data="upload_photo")
    builder.button(text="🎬 Загрузить видео", callback_data="upload_video")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def get_settings_keyboard(
    current_model: str = "flash",
    current_video_model: str = "v3_std",
    current_i2v_model: str = "v3_std",
    image_service: str = "novita",
):
    """Клавиатура настроек (для совместимости)"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад в главное меню", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def get_category_keyboard(category: str, presets: list, user_credits: int):
    """Клавиатура выбора пресета"""
    builder = InlineKeyboardBuilder()
    for preset in presets:
        affordable = "✅" if user_credits >= preset.cost else "❌"
        builder.button(
            text=f"{preset.name} — {preset.cost}🍌 {affordable}",
            callback_data=f"preset_{preset.id}",
        )
    builder.button(text="🔙 Назад в меню", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def get_preset_action_keyboard(preset_id: str, has_input: bool, category: str = None):
    """Действия с пресетом"""
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
    builder.adjust(2, 1)
    return builder.as_markup()


def get_duration_keyboard(preset_id: str, current_duration: int = 5):
    """Клавиатура выбора длительности"""
    builder = InlineKeyboardBuilder()
    for dur in [5, 10, 15]:
        emoji = "✅" if dur == current_duration else ""
        builder.button(
            text=f"{dur} сек {emoji}", callback_data=f"duration_{preset_id}_{dur}"
        )
    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    builder.adjust(2)
    return builder.as_markup()


def get_aspect_ratio_keyboard(preset_id: str, current_ratio: str = "16:9"):
    """Клавиатура выбора формата"""
    builder = InlineKeyboardBuilder()
    for ratio, label in [("16:9", "📺"), ("9:16", "📱"), ("1:1", "⬜")]:
        emoji = "✅" if ratio == current_ratio else ""
        builder.button(
            text=f"{label} {emoji}", callback_data=f"ratio_{preset_id}_{ratio}"
        )
    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    builder.adjust(1)
    return builder.as_markup()


def get_image_aspect_ratio_keyboard(preset_id: str, current_ratio: str = "1:1"):
    """Клавиатура выбора формата изображения"""
    builder = InlineKeyboardBuilder()
    for ratio, label in [
        ("1:1", "⬜"),
        ("16:9", "📺"),
        ("9:16", "📱"),
        ("4:5", "📸"),
        ("21:9", "🎬"),
    ]:
        emoji = "✅" if ratio == current_ratio else ""
        builder.button(
            text=f"{label} ({ratio}) {emoji}",
            callback_data=f"img_ratio_{preset_id}_{ratio}",
        )
    builder.button(text="🔙 Назад", callback_data=f"model_{preset_id}")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_model_selection_keyboard(preset_id: str, current_model: str = None):
    """Клавиатура выбора модели"""
    builder = InlineKeyboardBuilder()
    builder.button(text="⚡ Nano Banana Flash", callback_data=f"model_{preset_id}_flash")
    builder.button(text="💎 Nano Banana Pro", callback_data=f"model_{preset_id}_pro")
    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    builder.adjust(1)
    return builder.as_markup()


def get_resolution_keyboard(preset_id: str, current_resolution: str = "1K"):
    """Клавиатура выбора разрешения"""
    builder = InlineKeyboardBuilder()
    for res, label in [("1K", "⚡"), ("2K", "💎"), ("4K", "👑")]:
        emoji = "✅" if res == current_resolution else ""
        builder.button(
            text=f"{label} {res} {emoji}", callback_data=f"resolution_{preset_id}_{res}"
        )
    builder.button(text="🔙 Назад", callback_data=f"model_{preset_id}")
    builder.adjust(1)
    return builder.as_markup()


def get_quality_keyboard(preset_id: str):
    """Клавиатура выбора качества"""
    builder = InlineKeyboardBuilder()
    builder.button(text="⚡ Standard", callback_data=f"quality_{preset_id}_std")
    builder.button(text="💎 Pro", callback_data=f"quality_{preset_id}_pro")
    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    builder.adjust(1)
    return builder.as_markup()


def get_video_options_keyboard(preset_id: str):
    """Клавиатура опций видео"""
    builder = InlineKeyboardBuilder()
    builder.button(text="⏱ Длительность", callback_data=f"opt_duration_{preset_id}")
    builder.button(text="📐 Формат", callback_data=f"opt_ratio_{preset_id}")
    builder.button(text="▶️ Запустить", callback_data=f"run_{preset_id}")
    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    builder.adjust(2, 2)
    return builder.as_markup()


def get_video_options_no_preset_keyboard(
    current_duration: int = 5, current_ratio: str = "16:9", current_audio: bool = True
):
    """Клавиатура опций видео без пресета"""
    builder = InlineKeyboardBuilder()
    for dur in [5, 10, 15]:
        emoji = "✅" if dur == current_duration else ""
        builder.button(
            text=f"⏱ {dur}с {emoji}", callback_data=f"no_preset_duration_{dur}"
        )
    for ratio, label in [("16:9", "📺"), ("9:16", "📱"), ("1:1", "⬜")]:
        emoji = "✅" if ratio == current_ratio else ""
        builder.button(
            text=f"{label} {emoji}",
            callback_data=f"no_preset_ratio_{ratio.replace(':', '_')}",
        )
    builder.button(text="▶️ Запустить", callback_data="run_no_preset_video")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(3, 3, 1, 1)
    return builder.as_markup()


def get_confirm_generation_keyboard(cost: int, generation_type: str = "image"):
    """Подтверждение генерации"""
    builder = InlineKeyboardBuilder()
    if generation_type == "image":
        builder.button(
            text=f"🚀 Сгенерировать ({cost}🍌)", callback_data="run_generation"
        )
    else:
        builder.button(
            text=f"🎬 Создать видео ({cost}🍌)", callback_data="run_generation"
        )
    builder.button(text="⚙️ Изменить параметры", callback_data="back_to_params")
    builder.button(text="❌ Отмена", callback_data="back_main")
    builder.adjust(1, 2, 1)
    return builder.as_markup()


# Legacy алиасы
def get_settings_main_keyboard(
    current_image_service: str = "novita", current_video_model: str = "v3_std"
):
    return get_settings_keyboard(
        "flash", current_video_model, "v3_std", current_image_service
    )


def get_settings_images_keyboard(
    current_service: str = "novita", current_model: str = "flux_pro"
):
    return get_settings_keyboard(current_model, "v3_std", "v3_std", current_service)


def get_settings_video_keyboard(current_model: str = "v3_std"):
    return get_settings_keyboard("flash", current_model, "v3_std", "novita")


def get_settings_i2v_keyboard(current_model: str = "v3_std"):
    return get_settings_keyboard("flash", "v3_std", current_model, "novita")


def get_settings_keyboard_with_ali(
    current_model: str = "flash",
    current_video_model: str = "v3_std",
    current_i2v_model: str = "v3_std",
    image_service: str = "novita",
):
    return get_settings_keyboard(
        current_model, current_video_model, current_i2v_model, image_service
    )


def get_settings_keyboard_with_ai(
    current_model: str = "flash",
    current_video_model: str = "v3_std",
    current_i2v_model: str = "v3_std",
    image_service: str = "novita",
):
    return get_settings_keyboard(
        current_model, current_video_model, current_i2v_model, image_service
    )


def get_image_models_inline_keyboard(current_service: str = "flux_pro"):
    """Выбор модели для изображений"""
    builder = InlineKeyboardBuilder()
    for service, label in [
        ("flux_pro", "✨ FLUX.2 Pro"),
        ("nanobanana", "🍌 Nano Banana"),
        ("banana_pro", "💎 Banana Pro"),
        ("seedream", "🎨 Seedream"),
    ]:
        cost = IMAGE_COSTS.get(service, 3)
        check = "✅ " if service == current_service else ""
        builder.button(
            text=f"{check}{label} • {cost}🍌", callback_data=f"model_select_{service}"
        )
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()




def get_aspect_ratio_inline_keyboard(current_ratio: str = "1:1"):
    """Выбор формата"""
    builder = InlineKeyboardBuilder()
    for ratio, label in [("1:1", "⬜ 1:1"), ("16:9", "📺 16:9"), ("9:16", "📱 9:16")]:
        check = "✅ " if ratio == current_ratio else ""
        builder.button(text=f"{check}{label}", callback_data=f"ratio_select_{ratio}")
    builder.button(text="🔄 Назад к моделям", callback_data="back_to_models")
    builder.adjust(1)
    return builder.as_markup()


def get_video_params_inline_keyboard(
    current_duration: int = 5, current_ratio: str = "16:9"
):
    """Параметры видео"""
    builder = InlineKeyboardBuilder()
    builder.button(text="⏱ Длительность:", callback_data="back_main")
    for dur in [5, 10, 15]:
        check = "✅" if dur == current_duration else ""
        builder.button(text=f"{dur} сек {check}", callback_data=f"video_dur_{dur}")
    builder.button(text="📐 Формат:", callback_data="back_main")
    for ratio, emoji in [("16:9", "📺"), ("9:16", "📱"), ("1:1", "⬜")]:
        check = "✅" if ratio == current_ratio else ""
        builder.button(
            text=f"{emoji} {ratio} {check}", callback_data=f"video_ratio_{ratio}"
        )
    builder.button(text="🔙 Назад к моделям", callback_data="back_to_video_models")
    builder.adjust(1, 3, 1, 3)
    return builder.as_markup()


# =============================================================================
# ДОПОЛНИТЕЛЬНЫЕ КЛАВИАТУРЫ ДЛЯ СОВМЕСТИМОСТИ С generation.py
# =============================================================================


def get_advanced_options_keyboard(preset_id: str = None, current_options: dict = None):
    """Клавиатура расширенных опций генерации"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔙 Назад",
        callback_data=f"preset_{preset_id}" if preset_id else "back_main",
    )
    builder.adjust(1)
    return builder.as_markup()


def get_video_edit_keyboard(
    input_type: str = "video",
    quality: str = "std",
    duration: int = 5,
    aspect_ratio: str = "16:9",
):
    """Клавиатура опций видео-эффектов"""
    builder = InlineKeyboardBuilder()

    quality_emoji = "💎" if quality == "pro" else "⚡"
    builder.button(
        text=f"Качество: {quality_emoji} {quality.upper()}", callback_data="back_main"
    )
    builder.button(text="⚡ Standard", callback_data="video_edit_quality_std")
    builder.button(text="💎 Pro", callback_data="video_edit_quality_pro")

    builder.button(text="⏱ Длительность:", callback_data="back_main")
    builder.button(text="5 сек", callback_data="video_edit_duration_5")
    builder.button(text="10 сек", callback_data="video_edit_duration_10")

    builder.button(text="📐 Формат:", callback_data="back_main")
    builder.button(text="16:9", callback_data="video_edit_ratio_16_9")
    builder.button(text="9:16", callback_data="video_edit_ratio_9_16")
    builder.button(text="1:1", callback_data="video_edit_ratio_1_1")

    builder.button(text="🔄 Изменить тип", callback_data="video_edit_change_type")
    builder.button(text="▶️ Запустить", callback_data="run_video_edit")
    builder.button(text="🔙 Назад", callback_data="edit_video")

    builder.adjust(1, 2, 1, 2, 1, 3, 1, 2, 1)
    return builder.as_markup()


def get_video_edit_input_type_keyboard():
    """Клавиатура выбора типа ввода для видео-эффектов"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🎬 Видео", callback_data="video_edit_input_video")
    builder.button(text="🖼 Фото", callback_data="video_edit_input_image")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def get_multiturn_keyboard(preset_id: str):
    """Клавиатура после генерации изображения"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def get_prompt_tips_keyboard():
    """Клавиатура подсказок по промптам"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def get_reference_images_keyboard(preset_id: str = None):
    """Клавиатура работы с референсными изображениями"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📎 Загрузить референсы", callback_data=f"ref_upload_{preset_id}"
    )
    builder.button(text="🗑 Очистить", callback_data=f"ref_clear_{preset_id}")
    builder.button(text="✅ Подтвердить", callback_data=f"ref_confirm_{preset_id}")
    builder.button(
        text="🔙 Назад",
        callback_data=f"preset_{preset_id}" if preset_id else "back_main",
    )
    builder.adjust(1)
    return builder.as_markup()


def get_reference_images_upload_keyboard(
    current_count: int = 0, max_count: int = 14, preset_id: str = None
):
    """Клавиатура загрузки референсных изображений"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"Загружено: {current_count}/{max_count}", callback_data="back_main"
    )

    # Проверяем, video это или image
    is_video = preset_id and (preset_id.startswith("video") or preset_id == "video_new")

    # Для video_new используем те же callbacks что для image_new
    is_video_new = preset_id == "video_new"

    if is_video or is_video_new:
        # Для video_new используем те же callbacks что для image_new
        if is_video_new:
            builder.button(text="⏭ Пропустить", callback_data="img_ref_skip_new")
            builder.button(text="✅ Продолжить", callback_data="img_ref_continue_new")
        else:
            builder.button(text="⏭ Пропустить", callback_data="vid_ref_skip")
            builder.button(
                text="✅ Продолжить", callback_data=f"vid_ref_confirm_{preset_id}"
            )
        builder.button(text="🔙 Назад", callback_data="back_main")
        builder.adjust(1, 2, 1)
    else:
        # Для изображений - добавляем кнопку пропуска (используем _new для нового UX)
        if preset_id == "new":
            builder.button(text="⏭ Пропустить", callback_data="img_ref_skip_new")
            # Используем img_ref_continue_new для нового UX (без промежуточного экрана подтверждения)
            builder.button(text="✅ Продолжить", callback_data="img_ref_continue_new")
        else:
            builder.button(text="⏭ Пропустить", callback_data="img_ref_skip")
            builder.button(
                text="✅ Продолжить", callback_data=f"ref_confirm_{preset_id}"
            )
        builder.button(
            text="🔙 Назад",
            callback_data=(
                f"preset_{preset_id}"
                if preset_id and preset_id != "new"
                else "back_main"
            ),
        )
        builder.adjust(1, 2, 1)
    return builder.as_markup()


def get_reference_images_confirmation_keyboard(preset_id: str = None):
    """Клавиатура подтверждения референсов"""
    builder = InlineKeyboardBuilder()

    # Для нового UX (preset_id == "new") используем правильные callback_data
    if preset_id == "new":
        builder.button(text="🔄 Перезагрузить", callback_data="ref_reload_new")
        builder.button(text="✅ Подтвердить", callback_data="ref_confirm_new")
    else:
        builder.button(text="🔄 Перезагрузить", callback_data=f"ref_reload_{preset_id}")
        builder.button(text="✅ Подтвердить", callback_data=f"ref_accept_{preset_id}")

    # Используем back_main для нового UX (preset_id == "new")
    builder.button(
        text="🔙 Назад",
        callback_data=(
            f"ref_upload_{preset_id}"
            if preset_id and preset_id != "new"
            else "back_main"
        ),
    )
    builder.adjust(2, 1)
    return builder.as_markup()


def get_image_aspect_ratio_no_preset_keyboard(current_ratio: str = "1:1"):
    """Клавиатура выбора формата изображения без пресета"""
    builder = InlineKeyboardBuilder()
    for ratio, label in [
        ("1:1", "⬜ 1:1"),
        ("16:9", "📺 16:9"),
        ("9:16", "📱 9:16"),
        ("4:3", "📐 4:3"),
        ("3:2", "📐 3:2"),
    ]:
        check = "✅" if ratio == current_ratio else ""
        builder.button(
            text=f"{label} {check}",
            callback_data=f"img_ratio_no_preset_{ratio.replace(':', '_')}",
        )
    builder.button(
        text="📎 Загрузить референсы", callback_data="img_ref_upload_no_preset"
    )
    builder.button(text="🚀 Запустить", callback_data="run_no_preset_image")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(2, 2, 1, 2, 1, 1)
    return builder.as_markup()


def get_image_aspect_ratio_no_preset_edit_keyboard(current_ratio: str = "1:1"):
    """Клавиатура выбора формата для редактирования без пресета"""
    builder = InlineKeyboardBuilder()
    for ratio, label in [
        ("1:1", "⬜ 1:1"),
        ("16:9", "📺 16:9"),
        ("9:16", "📱 9:16"),
        ("4:3", "📐 4:3"),
        ("3:2", "📐 3:2"),
    ]:
        check = "✅" if ratio == current_ratio else ""
        builder.button(
            text=f"{label} {check}",
            callback_data=f"img_ratio_no_preset_edit_{ratio.replace(':', '_')}",
        )
    builder.button(text="🚀 Запустить", callback_data="run_no_preset_edit_image")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(2, 2, 1, 2, 1)
    return builder.as_markup()


def get_search_grounding_keyboard(preset_id: str = None, enabled: bool = False):
    """Клавиатура поискового заземления (Grounding)"""
    builder = InlineKeyboardBuilder()
    status = "🟢 ВКЛ" if enabled else "🔴 ВЫКЛ"
    builder.button(text=f"🔍 Поиск: {status}", callback_data=f"grounding_{preset_id}")
    builder.button(
        text="🔙 Назад",
        callback_data=f"preset_{preset_id}" if preset_id else "back_main",
    )
    builder.adjust(1)
    return builder.as_markup()


def get_image_editing_options_keyboard(preset_id: str = None):
    """Клавиатура опций редактирования изображения"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔙 Назад",
        callback_data=f"preset_{preset_id}" if preset_id else "back_main",
    )
    builder.adjust(1)
    return builder.as_markup()


def get_video_effects_model_keyboard(current_model: str = "v3_omni_std"):
    """Клавиатура выбора модели для видео-эффектов"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="edit_video")
    builder.adjust(1)
    return builder.as_markup()





def get_image_generation_model_keyboard(current_service: str = "flux_pro"):
    """Клавиатура выбора модели для генерации изображений"""
    builder = InlineKeyboardBuilder()
    for service, label, cost in [
        ("flux_pro", "✨ FLUX.2 Pro", 3),
        ("nanobanana", "🍌 Nano Banana", 3),
        ("banana_pro", "💎 Banana Pro", 5),
        ("seedream", "🎨 Seedream", 3),
    ]:
        check = "✅ " if service == current_service else ""
        builder.button(
            text=f"{check}{label} • {cost}🍌", callback_data=f"img_gen_model_{service}"
        )
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def get_image_with_references_model_keyboard(current_service: str = "flux_pro"):
    """Клавиатура выбора модели для генерации с референсами"""
    builder = InlineKeyboardBuilder()
    for service, label, cost in [
        ("flux_pro", "✨ FLUX.2 Pro", 3),
        ("banana_pro", "💎 Banana Pro", 5),
    ]:
        check = "✅ " if service == current_service else ""
        builder.button(
            text=f"{check}{label} • {cost}🍌", callback_data=f"ref_model_{service}"
        )
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def get_references_upload_keyboard(
    preset_id: str = None, back_callback: str = "back_main"
):
    """Клавиатура для загрузки референсных изображений перед генерацией"""
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ Пропустить", callback_data="img_ref_skip")
    builder.button(text="🔙 Назад", callback_data=back_callback)
    builder.adjust(2)
    return builder.as_markup()


def get_image_options_keyboard(
    current_service: str = "flux_pro", current_ratio: str = "1:1"
):
    """Клавиатура выбора опций изображения (модель, формат) - без кнопки создания, переход к промпту"""
    builder = InlineKeyboardBuilder()

    # Модели - из price.json
    novita_cost = IMAGE_COSTS.get("flux_pro", 3)
    nano_cost = IMAGE_COSTS.get("nanobanana", 3)
    pro_cost = IMAGE_COSTS.get("banana_pro", 5)
    seedream_cost = IMAGE_COSTS.get("seedream", 3)
    z5_cost = IMAGE_COSTS.get("z_image_turbo_lora", 3)

    novita_check = "✅ " if current_service == "flux_pro" else ""
    nano_check = "✅ " if current_service == "nanobanana" else ""
    pro_check = "✅ " if current_service == "banana_pro" else ""
    seedream_check = "✅ " if current_service == "seedream" else ""
    z5_check = "✅ " if current_service == "z_image_turbo_lora" else ""

    builder.button(
        text=f"{novita_check}✨ FLUX.2 Pro • {novita_cost}🍌",
        callback_data="opt_model_flux_pro",
    )
    builder.button(
        text=f"{nano_check}🍌 Nano Banana • {nano_cost}🍌",
        callback_data="opt_model_nanobanana",
    )
    builder.button(
        text=f"{pro_check}💎 Banana Pro • {pro_cost}🍌",
        callback_data="opt_model_banana_pro",
    )
    builder.button(
        text=f"{seedream_check}🎨 Seedream • {seedream_cost}🍌",
        callback_data="opt_model_seedream",
    )
    builder.button(
        text=f"{z5_check}🚀 Z5 Lora • {z5_cost}🍌",
        callback_data="opt_model_z_image_turbo_lora",
    )

    # Размер
    r1_1 = "✅ " if current_ratio == "1:1" else ""
    r16_9 = "✅ " if current_ratio == "16:9" else ""
    r9_16 = "✅ " if current_ratio == "9:16" else ""
    r4_3 = "✅ " if current_ratio == "4:3" else ""
    r3_2 = "✅ " if current_ratio == "3:2" else ""

    builder.button(text=f"{r1_1}1:1", callback_data="img_opt_ratio_1_1")
    builder.button(text=f"{r16_9}16:9", callback_data="img_opt_ratio_16_9")
    builder.button(text=f"{r9_16}9:16", callback_data="img_opt_ratio_9_16")
    builder.button(text=f"{r4_3}4:3", callback_data="img_opt_ratio_4_3")
    builder.button(text=f"{r3_2}3:2", callback_data="img_opt_ratio_3_2")

    # Кнопка перехода к вводу промпта
    builder.button(text="➡️ Ввести промпт", callback_data="img_prompt_input")

    builder.adjust(1, 1, 1, 1, 1, 1, 5, 1)
    return builder.as_markup()


def get_video_options_keyboard(
    current_model: str = "v3_std",
    current_duration: int = 5,
    current_ratio: str = "16:9",
):
    """Клавиатура выбора опций видео - без кнопки создания, переход к промпту"""
    builder = InlineKeyboardBuilder()

    # Модели - из price.json
    v26_data = VIDEO_COSTS.get("v26_pro", {"base": 8, "duration_costs": {"5": 8}})
    v3_std_data = VIDEO_COSTS.get("v3_std", {"base": 6, "duration_costs": {"5": 6}})
    v3_pro_data = VIDEO_COSTS.get("v3_pro", {"base": 8, "duration_costs": {"5": 8}})
    omni_data = VIDEO_COSTS.get("v3_omni_std", {"base": 8, "duration_costs": {"5": 8}})
    v26_motion_data = VIDEO_COSTS.get(
        "v26_motion_pro", {"base": 10, "duration_costs": {"5": 10}}
    )

    v26_cost = v26_data.get("duration_costs", {}).get(
        str(current_duration), v26_data.get("base", 8)
    )
    v3_std_cost = v3_std_data.get("duration_costs", {}).get(
        str(current_duration), v3_std_data.get("base", 6)
    )
    v3_pro_cost = v3_pro_data.get("duration_costs", {}).get(
        str(current_duration), v3_pro_data.get("base", 8)
    )
    omni_cost = omni_data.get("duration_costs", {}).get(
        str(current_duration), omni_data.get("base", 8)
    )
    v26_motion_cost = v26_motion_data.get("duration_costs", {}).get(
        str(current_duration), v26_motion_data.get("base", 10)
    )

    v26_check = "✅ " if current_model == "v26_pro" else ""
    v3_std_check = "✅ " if current_model == "v3_std" else ""
    v3_pro_check = "✅ " if current_model == "v3_pro" else ""
    omni_check = "✅ " if "omni" in current_model else ""
    v26_motion_check = "✅ " if current_model == "v26_motion_pro" else ""

    builder.button(
        text=f"{v3_std_check}⚡ Kling 3 Std • {v3_std_cost}🍌",
        callback_data="opt_v_model_v3_std",
    )
    builder.button(
        text=f"{v3_pro_check}💎 Kling 3 Pro • {v3_pro_cost}🍌",
        callback_data="opt_v_model_v3_pro",
    )


    # Размер
    r1_1 = "✅ " if current_ratio == "1:1" else ""
    r16_9 = "✅ " if current_ratio == "16:9" else ""
    r9_16 = "✅ " if current_ratio == "9:16" else ""
    r4_3 = "✅ " if current_ratio == "4:3" else ""
    r3_2 = "✅ " if current_ratio == "3:2" else ""

    builder.button(text=f"{r1_1}1:1", callback_data="opt_v_ratio_1_1")
    builder.button(text=f"{r16_9}16:9", callback_data="opt_v_ratio_16_9")
    builder.button(text=f"{r9_16}9:16", callback_data="opt_v_ratio_9_16")
    builder.button(text=f"{r4_3}4:3", callback_data="opt_v_ratio_4_3")
    builder.button(text=f"{r3_2}3:2", callback_data="opt_v_ratio_3_2")

    # Длительность
    d5 = "✅ " if current_duration == 5 else ""
    d10 = "✅ " if current_duration == 10 else ""
    d15 = "✅ " if current_duration == 15 else ""

    builder.button(text=f"{d5}5 сек", callback_data="opt_v_dur_5")
    builder.button(text=f"{d10}10 сек", callback_data="opt_v_dur_10")
    builder.button(text=f"{d15}15 сек", callback_data="opt_v_dur_15")

    # Кнопка перехода к вводу промпта
    builder.button(text="✅ Далее", callback_data="vid_prompt_input")
    builder.adjust(1, 1, 1, 1, 1, 5, 3, 1)
    return builder.as_markup()


def get_image_to_video_model_keyboard(current_model: str = "v3_omni_std"):
    """Клавиатура выбора модели для создания видео из фото"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()



def get_motion_control_keyboard(current_mode: str = "1080p", current_orientation: str = "video"):
    """Клавиатура опций Motion Control"""
    builder = InlineKeyboardBuilder()

    # Mode
    mode_720p = "✅ " if current_mode == "720p" else ""
    mode_1080p = "✅ " if current_mode == "1080p" else ""
    builder.button(text=f"{mode_720p}📱 720p (std)", callback_data="motion_mode_720p")
    builder.button(text=f"{mode_1080p}🖥 1080p (pro)", callback_data="motion_mode_1080p")

    # Orientation
    orient_image = "✅ " if current_orientation == "image" else ""
    orient_video = "✅ " if current_orientation == "video" else ""
    builder.button(text=f"{orient_image}🖼 Image orient", callback_data="motion_orientation_image")
    builder.button(text=f"{orient_video}🎬 Video orient", callback_data="motion_orientation_video")

    # Buttons
    builder.button(text="🚀 Создать видео", callback_data="run_motion_control")
    builder.button(text="🔙 Главное меню", callback_data="back_main")

    builder.adjust(2, 2, 2)
    return builder.as_markup()


def get_motion_upload_keyboard(step: str):
    """Клавиатура для загрузки файлов Motion Control"""
    builder = InlineKeyboardBuilder()
    if step == "image":
        builder.button(text="🖼 Загрузить изображение персонажа", callback_data="motion_upload_image")
        builder.button(text="⏭ Пропустить (позже)", callback_data="motion_skip_image")
    elif step == "video":
        builder.button(text="🎬 Загрузить видео движения", callback_data="motion_upload_video")
        builder.button(text="⏭ Пропустить (позже)", callback_data="motion_skip_video")
    builder.button(text="🔙 Главное меню", callback_data="back_main")
    builder.adjust(1, 1)
    return builder.as_markup()


def get_video_in_video_keyboard(
    quality: str = "std",
    duration: int = 5,
    aspect_ratio: str = "16:9",
):
    """Клавиатура опций видео в видео"""
    builder = InlineKeyboardBuilder()

    quality_emoji = "💎" if quality == "pro" else "⚡"
    builder.button(
        text=f"Качество: {quality_emoji} {quality.upper()}",
        callback_data="viov_change_quality",
    )
    builder.button(text="⚡ Standard", callback_data="viov_quality_std")
    builder.button(text="💎 Pro", callback_data="viov_quality_pro")

    builder.button(text="⏱ Длительность:", callback_data="viov_change_duration")
    builder.button(text="5 сек", callback_data="viov_duration_5")
    builder.button(text="10 сек", callback_data="viov_duration_10")

    builder.button(text="📐 Формат:", callback_data="viov_change_ratio")
    builder.button(text="16:9", callback_data="viov_ratio_16_9")
    builder.button(text="9:16", callback_data="viov_ratio_9_16")
    builder.button(text="1:1", callback_data="viov_ratio_1_1")

    builder.button(text="📎 Загрузить видео", callback_data="viov_upload_video")
    builder.button(text="▶️ Запустить", callback_data="run_video_in_video")
    builder.button(text="🔙 Назад", callback_data="back_main")

    builder.adjust(1, 2, 1, 2, 1, 3, 1, 2, 1)
    return builder.as_markup()


def get_video_edit_confirm_keyboard():
    """Клавиатура подтверждения видео-эффектов"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="run_video_edit")
    builder.button(text="❌ Отмена", callback_data="edit_video")
    builder.adjust(2)
    return builder.as_markup()
