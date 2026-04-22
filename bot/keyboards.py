import logging
import os

from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.services.preset_manager import preset_manager

logger = logging.getLogger(__name__)


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


SUPPORTED_RATIOS = {
    "v3_std": ["16:9", "9:16", "1:1"],
    "v3_pro": ["16:9", "9:16", "1:1"],
    "v3_omni_std": ["16:9", "9:16", "1:1"],
    "v3_omni_pro": ["16:9", "9:16", "1:1"],
    "grok_imagine": ["16:9", "9:16", "1:1", "3:2", "2:3"],
    "aleph": ["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
    "runway": ["16:9", "9:16", "1:1"],
    "glow": ["16:9", "9:16", "1:1"],
    "seedance2": ["16:9", "9:16", "1:1"],
}


def get_create_video_keyboard(
    current_v_type: str = "text",
    current_model: str = "v3_std",
    current_ratio: str = "16:9",
    current_duration: int = 5,
    current_mode: str = "720p",
    current_orientation: str = "video",
    current_video_model: str = None,  # Алиас для обратной совместимости
    current_grok_mode: str = "normal",
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

    # Модели - цены из preset_manager (синхронно с списанием)
    v26_cost = preset_manager.get_video_cost("v26_pro", current_duration)
    v3_std_cost = preset_manager.get_video_cost("v3_std", current_duration)
    v3_pro_cost = preset_manager.get_video_cost("v3_pro", current_duration)
    omni_cost = preset_manager.get_video_cost("v3_omni_std", current_duration)
    v3_omni_pro_cost = preset_manager.get_video_cost("v3_omni_pro", current_duration)
    v26_motion_cost = preset_manager.get_video_cost("v26_motion_pro", current_duration)
    grok_cost = preset_manager.get_video_cost("grok_imagine", current_duration)

    seedance_cost = preset_manager.get_video_cost("seedance2", current_duration)
    runway_cost = preset_manager.get_video_cost("runway", current_duration)
    aleph_cost = preset_manager.get_video_cost("aleph", current_duration)
    glow_cost = preset_manager.get_video_cost("glow", current_duration)

    if current_v_type == "video":
        models = [
            {
                "key": "aleph",
                "label": "🔮 Aleph Video (требует видео реф.)",
                "cost": aleph_cost,
            },
            {
                "key": "glow",
                "label": "✨ Kling Glow (требует видео реф.)",
                "cost": glow_cost,
            },
        ]
    else:
        models = [
            {"key": "v3_std", "label": "⚡ Kling 3 Std", "cost": v3_std_cost},
            {"key": "v3_pro", "label": "💎 Kling 3 Pro", "cost": v3_pro_cost},
        ]
        if current_v_type != "text":
            models.append(
                {
                    "key": "seedance2",
                    "label": "🌱 Seedance 2.0",
                    "cost": seedance_cost,
                }
            )
        models.append(
            {
                "key": "runway",
                "label": "🎥 Runway AI",
                "cost": runway_cost,
            }
        )
        models.append(
            {
                "key": "grok_imagine",
                "label": "🧠 Grok Imagine",
                "cost": grok_cost,
            }
        )

    for model_info in models:
        check = "✅ " if current_model == model_info["key"] else ""
        builder.button(
            text=f"{check}{model_info['label']} • {model_info['cost']}🍌",
            callback_data=f"v_model_{model_info['key']}",
        )

    # Размер - только поддерживаемые моделью
    supported_ratios = SUPPORTED_RATIOS.get(current_model, ["16:9", "9:16", "1:1"])
    ratio_buttons = []
    for ratio in supported_ratios:
        check = "✅ " if current_ratio == ratio else ""
        label = ratio.replace(":", "∶")  # визуально лучше
        ratio_buttons.append(
            InlineKeyboardButton(
                text=f"{check}{label}", callback_data=f"ratio_{ratio.replace(':', '_')}"
            )
        )
    builder.row(*ratio_buttons)

    # Длительности: показываем только поддерживаемые моделью значения
    model_data_for_durations = (
        preset_manager._price_config.get("costs_reference", {})
        .get("video_models", {})
        .get(current_model, {})
    )
    duration_costs = model_data_for_durations.get("duration_costs", {})
    if duration_costs:
        available_durations = sorted([int(k) for k in duration_costs.keys()])
    else:
        available_durations = [5, 10, 15]

    for dur in available_durations:
        check = "✅ " if current_duration == dur else ""
        builder.button(text=f"{check}{dur} сек", callback_data=f"video_dur_{dur}")

    # Grok Imagine modes
    if current_model == "grok_imagine":
        normal_check = "✅ " if current_grok_mode == "normal" else ""
        fun_check = "✅ " if current_grok_mode == "fun" else ""
        spicy_check = "✅ " if current_grok_mode == "spicy" else ""
        builder.button(text=f"{normal_check}Normal", callback_data="grok_mode_normal")
        builder.button(text=f"{fun_check}Fun 🎉", callback_data="grok_mode_fun")
        builder.button(text=f"{spicy_check}Spicy 🔥", callback_data="grok_mode_spicy")

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
    total_cost = preset_manager.get_video_cost(current_model, current_duration)

    # Кнопка создания - после выбора опций пользователь отправляет промпт
    builder.button(text=f"💰 {total_cost}🍌", callback_data="back_main")
    builder.button(text="🏠 Главное меню", callback_data="back_main")

    num_models = len(models)
    widths = [3] + [1] * num_models + [5, len(available_durations), 2]
    grok_width = 3 if current_model == "grok_imagine" else 0
    if current_v_type == "video":
        widths += [4, 2]
    if grok_width:
        widths += [grok_width]
    builder.adjust(*widths)
    return builder.as_markup()


def get_reference_videos_upload_keyboard(
    current_count: int = 0, max_count: int = 5, preset_id: str = None
):
    """Клавиатура загрузки референсных видео"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"Загружено: {current_count}/{max_count}", callback_data="back_main"
    )
    if preset_id == "video_new":
        builder.button(text="⏭ Пропустить", callback_data="vid_ref_skip_new")
        builder.button(text="✅ Продолжить", callback_data="vid_ref_continue_new")
    else:
        builder.button(text="⏭ Пропустить", callback_data="vid_ref_skip")
        builder.button(
            text="✅ Продолжить", callback_data=f"vid_ref_confirm_{preset_id}"
        )
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1, 2, 1)
    return builder.as_markup()


def get_reference_images_upload_keyboard(
    current_count: int = 0, max_count: int = 14, preset_id: str = None
):
    """Клавиатура загрузки референсных изображений"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"Загружено: {current_count}/{max_count}", callback_data="back_main"
    )
    if preset_id == "new":
        builder.button(text="⏭ Пропустить", callback_data="img_ref_skip_new")
        builder.button(text="✅ Продолжить", callback_data="img_ref_continue_new")
    elif preset_id == "generate_image":
        builder.button(text="⏭ Пропустить", callback_data="img_ref_skip")
        builder.button(
            text="✅ Продолжить", callback_data="img_ref_confirm_generate_image"
        )
    else:
        builder.button(text="⏭ Пропустить", callback_data="img_ref_skip")
        builder.button(
            text="✅ Продолжить", callback_data=f"img_ref_confirm_{preset_id}"
        )
    builder.button(text="🔄 Перезагрузить", callback_data="ref_reload_new")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1, 2, 2)
    return builder.as_markup()


# =============================================================================
# МЕНЮ СОЗДАНИЯ ФОТО - всё на одном экране
# =============================================================================


def get_create_image_keyboard(
    current_service: str = "flux_pro", current_ratio: str = "1:1", num_refs: int = 0
):
    """Меню создания фото - всё на одном экране"""
    builder = InlineKeyboardBuilder()

    # Модели - цены из preset_manager
    pro_cost = preset_manager.get_generation_cost("nano-banana-pro")
    banana2_cost = preset_manager.get_generation_cost("banana_2")
    seedream_5_lite_cost = preset_manager.get_generation_cost("seedream_5_lite")
    seedream_edit_cost = preset_manager.get_generation_cost("seedream_edit")

    pro_check = "✅ " if current_service == "nano-banana-pro" else ""
    banana2_check = "✅ " if current_service == "banana_2" else ""
    seedream_5_lite_check = "✅ " if current_service == "seedream_5_lite" else ""
    seedream_edit_check = "✅ " if current_service == "seedream_edit" else ""

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
    builder.button(
        text=f"{seedream_edit_check}🖌 Seedream 4.5 • {seedream_edit_cost}🍌",
        callback_data="model_seedream_edit",
    )

    # Размер
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

    builder.adjust(1, 1, 1, 1, 3, 2, 1)

    return builder.as_markup()


# =============================================================================
# МЕНЮ ПОПОЛНЕНИЯ
# =============================================================================


def get_topup_keyboard():
    """Меню пополнения баланса"""
    return get_payment_packages_keyboard(
        preset_manager.get_packages(), provider=config.payment_provider
    )


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
    builder = InlineKeyboardBuilder()
    # Всегда показываем оферту через внутренний callback — чтобы оферта была
    # доступна пользователю независимо от внешних настроек/хостинга.
    builder.button(text="📜 Публичная оферта", callback_data="partner_offer")
    builder.button(
        text="✔ Прочитал и согласен с условиями", callback_data="partner_accept"
    )
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1, 1, 1)
    return builder.as_markup()


# =============================================================================
# ДОПОЛНИТЕЛЬНЫЕ ФУНКЦИИ (для совместимости)
# =============================================================================


def get_settings_keyboard(
    current_model: str = "flash",
    current_video_model: str = "v3_std",
    current_i2v_model: str = "v3_std",
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


def get_advanced_options_keyboard():
    """Клавиатура расширенных опций (заглушка для исправления импорта)"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()
