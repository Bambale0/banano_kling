import json
import logging
import os

from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.image_models import (
    IMAGE_MODEL_ORDER,
    get_image_model_config,
    get_image_option_label,
    normalize_image_options,
    resolve_image_model,
)
from bot.services.preset_manager import preset_manager
from bot.video_models import (
    VIDEO_OPTION_LABELS,
    get_video_model_config,
    get_video_models_for_type,
    get_video_option_label,
    normalize_video_options,
)

logger = logging.getLogger(__name__)


def load_prices() -> dict:
    """Load price configuration from data/price.json.

    Backwards-compatible helper used by tests and older admin code. Runtime code
    primarily uses preset_manager, but keeping this helper makes keyboard module
    importable and easy to test.
    """
    price_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "price.json")
    with open(price_path, "r", encoding="utf-8") as f:
        return json.load(f)


try:
    PACKAGES = load_prices().get("packages", [])
except Exception:
    logger.exception("Failed to load package prices for keyboard fallback")
    PACKAGES = []


# =============================================================================
# ГЛАВНОЕ МЕНЮ - согласно ux.md
# =============================================================================


def get_main_menu_keyboard(user_credits: int = 0):
    """Главное меню бота - согласно ux.md"""
    builder = InlineKeyboardBuilder()

    builder.button(text="🧠 GPT 5.5", callback_data="menu_gpt55")
    builder.button(text="🎬 Создать видео", callback_data="create_video_new")
    builder.button(text="🖼 Создать фото", callback_data="create_image_refs_new")
    builder.button(text="📚 Каталог промтов", callback_data="menu_feed")
    builder.button(text="🌈 Микс фото", callback_data="quick_mix_photo")
    builder.button(text="🎯 Motion Control", callback_data="motion_control")
    builder.button(text="🔷 Gemini Omni", callback_data="gemini_omni_menu")
    builder.button(text="✍️ Улучшить промпт", callback_data="gpt55_improve_prompt")
    builder.button(text="📷 Фото → Промпт", callback_data="photo_to_prompt")
    builder.button(text="🍌 Мой баланс", callback_data="menu_balance")
    builder.button(text="💰 Купить бананы", callback_data="menu_topup")
    builder.button(text="💼 Партнёрам", callback_data="menu_partner")
    builder.button(text="🆘 Поддержка", callback_data="menu_support")

    builder.adjust(1, 2, 2, 2, 2, 2, 2)

    return builder.as_markup()


def get_admin_keyboard():
    """Админ-панель"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="📣 Рассылка", callback_data="admin_broadcast")
    builder.button(text="🍌 Баланс", callback_data="admin_users")
    builder.button(text="🎟 Промокоды", callback_data="admin_promos")
    builder.button(text="👤 Пользователь", callback_data="admin_users")
    builder.button(text="🚫 Бан / разбан", callback_data="admin_ban_menu")
    builder.button(text="📦 Экспорт пользователей", callback_data="admin_export_users")
    builder.button(text="⚙️ Техрежим", callback_data="admin_maintenance")
    builder.button(text="💰 Цены", callback_data="admin_prices")
    builder.button(text="🔄 Обновить", callback_data="admin_reload")
    builder.button(text="🏠 Домой", callback_data="back_main")
    builder.adjust(2, 2, 2, 2, 2, 1)
    return builder.as_markup()


def get_admin_prices_keyboard():
    """Категории цен"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🖼 Изображения", callback_data="admin_price_cat_image")
    builder.button(text="🎬 Видео", callback_data="admin_price_cat_video")
    builder.button(text="🔙 Назад", callback_data="admin_back")
    builder.adjust(2, 1)
    return builder.as_markup()


def get_admin_price_image_keyboard(price_config: dict):
    """Кнопки цен на изображения"""
    labels = {
        "gemini_2_5_flash": "Banana 2.5 Flash",
        "gemini_3_pro": "Banana 3 Pro",
        "banana_2": "Banana 2",
        "gpt_image_2": "GPT Image 2",
        "z_image_turbo": "Z Image Turbo",
        "seedream": "Seedream",
        "seedream_45": "Seedream 4.5",
        "nano-banana-pro": "Banana Pro",
        "seedream_lite": "Seedream Lite",
        "seedream_5_lite": "Seedream 5 Lite",
        "seedream_edit": "Seedream Edit",
        "grok_t2i": "Grok T2I",
        "grok_i2i": "Grok I2I",
        "ideogram_character": "Ideogram Character",
    }
    builder = InlineKeyboardBuilder()
    image_models = price_config.get("costs_reference", {}).get("image_models", {})
    for key, cost in image_models.items():
        name = labels.get(key, key)
        cb = f"admin_price_img_{key}"
        if len(cb) > 64:
            cb = cb[:64]
        builder.button(text=f"{name}: {cost}🍌", callback_data=cb)
    builder.button(text="🔙 Назад", callback_data="admin_prices")
    builder.adjust(2)
    return builder.as_markup()


def get_admin_price_video_keyboard(price_config: dict):
    """Кнопки цен на видео"""
    labels = {
        "v3_std": "Kling 3 Std",
        "v3_pro": "Kling 3 Pro",
        "v26_motion_std": "Kling 2.6 Motion Std",
        "v26_motion_pro": "Kling 2.6 Motion Pro",
        "seedance2": "Seedance 2.0",
        "grok_imagine": "Grok Imagine (vid)",
        "runway": "Runway AI",
        "aleph": "Aleph Video",
        "glow": "Kling Glow",
        "veo3_fast": "Veo 3.1 Fast",
        "veo3": "Veo 3.1 Pro",
        "veo3_lite": "Veo 3.1 Lite",
        "hailuo_23_pro": "Hailuo 2.3 Pro",
        "hailuo_23_std": "Hailuo 2.3 Std",
        "hailuo_pro": "Hailuo Pro",
        "hailuo_std": "Hailuo Std",
        "hailuo_i2v_pro": "Hailuo I2V Pro",
        "hailuo_i2v_std": "Hailuo I2V Std",
        "happyhorse_t2v": "HappyHorse T2V",
        "happyhorse_i2v": "HappyHorse I2V",
        "happyhorse_ref2v": "HappyHorse Ref2V",
        "happyhorse_edit": "HappyHorse Edit",
        "wan_27_t2v": "Wan 2.7 T2V",
        "wan_27_i2v": "Wan 2.7 I2V",
        "gemini_omni": "Gemini Omni",
    }
    builder = InlineKeyboardBuilder()
    video_models = price_config.get("costs_reference", {}).get("video_models", {})
    for key, model_data in video_models.items():
        name = labels.get(key, key)
        if "fixed_cost" in model_data:
            cost_str = f"{model_data['fixed_cost']}🍌"
        elif "per_second" in model_data:
            cost_str = f"{model_data['per_second']}🍌/с"
        else:
            base = model_data.get("base", "?")
            cost_str = f"от {base}🍌"
        cb = f"admin_price_vid_{key}"
        if len(cb) > 64:
            cb = cb[:64]
        builder.button(text=f"{name}: {cost_str}", callback_data=cb)
    builder.button(text="🔙 Назад", callback_data="admin_prices")
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
    # Veo 3.1
    "veo3_fast": ["16:9", "9:16"],
    "veo3": ["16:9", "9:16"],
    "veo3_lite": ["16:9", "9:16"],
    # Hailuo (fixed aspect ratio, shown as single option)
    "hailuo_23_pro": ["16:9"],
    "hailuo_23_std": ["16:9"],
    "hailuo_pro": ["16:9"],
    "hailuo_std": ["16:9"],
    "hailuo_i2v_pro": ["16:9"],
    "hailuo_i2v_std": ["16:9"],
    "happyhorse_t2v": ["16:9", "9:16", "1:1"],
    "happyhorse_i2v": ["16:9"],
    "happyhorse_ref2v": ["16:9", "9:16", "1:1"],
    "happyhorse_edit": ["16:9"],
    "wan_27_t2v": ["16:9", "9:16", "1:1"],
    "wan_27_i2v": [],
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
    current_hailuo_resolution: str = "768P",
    current_video_options: dict | None = None,
):
    """Меню создания видео - всё на одном экране"""
    # Если передан current_video_model, используем его
    if current_video_model is not None:
        current_model = current_video_model
    legacy_options = {
        "mode": current_grok_mode,
        "quality": current_mode,
        "motion_quality": current_mode,
        "character_orientation": current_orientation,
    }
    if current_model.startswith("hailuo"):
        legacy_options["resolution"] = current_hailuo_resolution
    if current_video_options:
        legacy_options.update(current_video_options)
    current_video_options = normalize_video_options(current_model, legacy_options)

    builder = InlineKeyboardBuilder()
    # Тип генерации - текст, фото+текст или видео+текст
    text_check = "✅ " if current_v_type == "text" else ""
    imgtxt_check = "✅ " if current_v_type == "imgtxt" else ""
    video_check = "✅ " if current_v_type == "video" else ""

    builder.row(
        InlineKeyboardButton(
            text=f"{text_check}📝 Текст → Видео", callback_data="v_type_text"
        ),
        InlineKeyboardButton(
            text=f"{imgtxt_check}🖼 Фото + Текст → Видео", callback_data="v_type_imgtxt"
        ),
        InlineKeyboardButton(
            text=f"{video_check}🎬 Видео + Текст → Видео (Motion Control)",
            callback_data="v_type_video",
        ),
    )

    models = []
    for model_id in get_video_models_for_type(current_v_type):
        model_config = get_video_model_config(model_id)
        models.append(
            {
                "key": model_id,
                "label": model_config["label"],
                "cost": preset_manager.get_video_cost(model_id, current_duration),
            }
        )

    model_buttons = []
    for model_info in models:
        check = "✅ " if current_model == model_info["key"] else ""
        model_buttons.append(
            InlineKeyboardButton(
                text=f"{check}{model_info['label']} • {model_info['cost']}🍌",
                callback_data=f"v_model_{model_info['key']}",
            )
        )
    builder.row(*model_buttons[:2])
    if len(model_buttons) > 2:
        for index in range(2, len(model_buttons), 2):
            builder.row(*model_buttons[index : index + 2])

    # Размер - только поддерживаемые моделью
    model_config = get_video_model_config(current_model)
    supported_ratios = model_config.get("aspect_ratios")
    if supported_ratios is None:
        supported_ratios = ["16:9", "9:16", "1:1"]
    ratio_buttons = []
    for ratio in supported_ratios:
        check = "✅ " if current_ratio == ratio else ""
        label = ratio.replace(":", "∶")  # визуально лучше
        ratio_buttons.append(
            InlineKeyboardButton(
                text=f"{check}{label}",
                callback_data=f"vratio_{ratio.replace(':', '_')}",
            )
        )
    for index in range(0, len(ratio_buttons), 3):
        builder.row(*ratio_buttons[index : index + 3])

    available_durations = model_config.get("durations") or []
    if available_durations:
        duration_buttons = []
        for dur in available_durations:
            check = "✅ " if current_duration == dur else ""
            duration_buttons.append(
                InlineKeyboardButton(
                    text=f"{check}{dur} сек", callback_data=f"vdur_{dur}"
                )
            )
        for index in range(0, len(duration_buttons), 4):
            builder.row(*duration_buttons[index : index + 4])

    # Дополнительные возможности модели: качество, разрешение, звук, режимы.
    for option_name, allowed_values in model_config.get("options", {}).items():
        option_label = VIDEO_OPTION_LABELS.get(option_name, option_name)
        buttons = []
        for value in allowed_values:
            value_token = str(value).lower()
            check = "✅ " if current_video_options.get(option_name) == value else ""
            buttons.append(
                InlineKeyboardButton(
                    text=f"{check}{option_label}: {get_video_option_label(option_name, value)}",
                    callback_data=f"vopt_{option_name}_{value_token}",
                )
            )
        row_size = 2 if len(buttons) <= 4 else 3
        for index in range(0, len(buttons), row_size):
            builder.row(*buttons[index : index + row_size])

    # Рассчитываем цену
    total_cost = preset_manager.get_video_cost(current_model, current_duration)

    # Кнопка создания - после выбора опций пользователь отправляет промпт
    builder.row(
        InlineKeyboardButton(text=f"💰 {total_cost}🍌", callback_data="back_main"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main"),
    )
    return builder.as_markup()


def get_gemini_omni_keyboard(
    audio_count: int = 0,
    character_count: int = 0,
    duration: int = 4,
    resolution: str = "720p",
    ratio: str = "16:9",
):
    """Самостоятельное меню Gemini Omni."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🎬 Запустить видео", callback_data="omni_start_video")
    builder.button(text="🖼+📹 Фото + видео", callback_data="omni_add_photo_video")
    builder.button(text="🖼 Добавить фото", callback_data="omni_add_photo")
    builder.button(text="📹 Добавить видео", callback_data="omni_add_video")
    for value in (4, 6, 8, 10):
        check = "✅ " if int(duration) == value else ""
        builder.button(text=f"{check}{value}с", callback_data=f"omni_duration_{value}")
    for value in ("720p", "1080p", "4k"):
        check = "✅ " if resolution == value else ""
        builder.button(text=f"{check}{value}", callback_data=f"omni_resolution_{value}")
    for value in ("16:9", "9:16"):
        check = "✅ " if ratio == value else ""
        builder.button(
            text=f"{check}{value}", callback_data=f"omni_ratio_{value.replace(':', '_')}"
        )
    builder.button(text="🎙 Голос", callback_data="omni_create_audio")
    builder.button(text="🧍 Персонаж", callback_data="omni_create_character")
    builder.button(
        text=f"➕ Voice ID {audio_count}/3", callback_data="omni_add_audio_id"
    )
    builder.button(
        text=f"➕ Char ID {character_count}/3",
        callback_data="omni_add_character_id",
    )
    builder.button(text="🌱 Seed", callback_data="omni_set_seed")
    builder.button(text="🧹 Очистить", callback_data="omni_clear_refs")
    builder.button(text="🏠 Главное", callback_data="back_main")
    builder.adjust(1, 1, 2, 4, 3, 2, 2, 2, 1)
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


def get_face_preservation_keyboard():
    """Клавиатура выбора режима сохранения лица для фото-референсов."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔒 Максимально сохранить", callback_data="face_mode_strict")
    builder.button(text="✨ Немного улучшить", callback_data="face_mode_enhance")
    builder.button(text="✅ Далее", callback_data="face_mode_none")
    builder.button(text="🔙 Назад", callback_data="img_ref_upload_new")
    builder.adjust(1, 1, 2)
    return builder.as_markup()


def get_prompt_safety_keyboard():
    """Клавиатура ручного выбора улучшения промпта перед генерацией."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🛡 Сделать безопасным", callback_data="image_prompt_safe")
    builder.button(text="✅ Оставить как есть", callback_data="image_prompt_original")
    builder.button(text="🔙 Назад", callback_data="image_prompt_back")
    builder.adjust(1, 1, 1)
    return builder.as_markup()


# =============================================================================
# МЕНЮ СОЗДАНИЯ ФОТО - всё на одном экране
# =============================================================================


def get_create_image_keyboard(
    current_service: str = "banana_pro",
    current_ratio: str = "1:1",
    num_refs: int = 0,
    current_options: dict | None = None,
    img_count: int = 1,
):
    """Меню создания фото - всё на одном экране"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🧬 Микс фото", callback_data="quick_mix_photo"))
    current_service = resolve_image_model(current_service)
    model_config = get_image_model_config(current_service)
    current_options = normalize_image_options(
        current_service, {"aspect_ratio": current_ratio, **(current_options or {})}
    )

    model_buttons = []
    for model_id in IMAGE_MODEL_ORDER:
        config = get_image_model_config(model_id)
        if config.get("requires_refs") and num_refs == 0:
            continue
        cost = preset_manager.get_generation_cost(config["cost_key"])
        check = "✅ " if current_service == model_id else ""
        model_buttons.append(
            InlineKeyboardButton(
                text=f"{check}{config['label']} • {cost}🍌",
                callback_data=f"img_model_{model_id}",
            )
        )
    for index in range(0, len(model_buttons), 2):
        builder.row(*model_buttons[index : index + 2])

    for option_name, allowed_values in model_config["options"].items():
        option_buttons = []
        current_value = current_options.get(option_name)
        for value in allowed_values:
            check = "✅ " if current_value == value else ""
            option_buttons.append(
                InlineKeyboardButton(
                    text=f"{check}{get_image_option_label(option_name, value)}",
                    callback_data=_get_image_option_callback(option_name, value),
                )
            )
        row_size = 3 if option_name == "aspect_ratio" else 2
        for index in range(0, len(option_buttons), row_size):
            builder.row(*option_buttons[index : index + row_size])

    # Кнопки выбора количества одновременных генераций (1-6)
    count_buttons = []
    for n in [1, 2, 3, 4, 5, 6]:
        check = "✅" if img_count == n else ""
        count_buttons.append(
            InlineKeyboardButton(
                text=f"{check}{n}×" if not check else f"✅{n}×",
                callback_data=f"img_count_{n}",
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="🔢 Количество генераций:", callback_data="img_count_info"
        )
    )
    builder.row(*count_buttons)

    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main"))
    return builder.as_markup()


def _get_image_option_callback(option_name: str, value) -> str:
    if isinstance(value, bool):
        suffix = "on" if value else "off"
    else:
        suffix = str(value).replace(":", "_").lower()
    return f"imgopt_{option_name}_{suffix}"


def get_settings_keyboard_with_ai(
    current_model: str = "flash",
    current_video_model: str = "v3_std",
    current_i2v_model: str = "v3_std",
    image_service: str = "banana_pro",
):
    builder = InlineKeyboardBuilder()
    image_service = resolve_image_model(image_service)

    image_buttons = []
    for model_id in IMAGE_MODEL_ORDER:
        config = get_image_model_config(model_id)
        if config.get("requires_refs"):
            continue
        check = "✅ " if image_service == model_id else ""
        image_buttons.append(
            InlineKeyboardButton(
                text=f"{check}{config['settings_label']}",
                callback_data=f"settings_service_{model_id}",
            )
        )
    for index in range(0, len(image_buttons), 2):
        builder.row(*image_buttons[index : index + 2])

    video_names = {
        "v3_std": "⚡ Kling 3 Std",
        "v3_pro": "💎 Kling 3 Pro",
        "runway": "🎥 Runway",
        "grok_imagine": "🧠 Grok Imagine",
        "seedance2": "🌱 Seedance 2.0",
    }
    video_buttons = []
    for model_id in ["v3_std", "v3_pro", "runway", "grok_imagine"]:
        check = "✅ " if current_video_model == model_id else ""
        video_buttons.append(
            InlineKeyboardButton(
                text=f"{check}{video_names[model_id]}",
                callback_data=f"settings_video_{model_id}",
            )
        )
    for index in range(0, len(video_buttons), 2):
        builder.row(*video_buttons[index : index + 2])

    i2v_buttons = []
    for model_id in ["v3_std", "v3_pro", "seedance2", "runway"]:
        check = "✅ " if current_i2v_model == model_id else ""
        i2v_buttons.append(
            InlineKeyboardButton(
                text=f"{check}{video_names.get(model_id, model_id)}",
                callback_data=f"settings_i2v_{model_id}",
            )
        )
    for index in range(0, len(i2v_buttons), 2):
        builder.row(*i2v_buttons[index : index + 2])

    builder.row(
        InlineKeyboardButton(text="💬 ИИ-ассистент", callback_data="menu_ai_settings")
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_main"))
    return builder.as_markup()


# =============================================================================
# МЕНЮ ПОПОЛНЕНИЯ
# =============================================================================


def get_topup_keyboard():
    """Меню пополнения баланса"""
    packages = PACKAGES or preset_manager.get_packages()
    return get_payment_packages_keyboard(packages, provider=config.payment_provider)


def get_payment_provider_keyboard(current_provider: str = "tbank"):
    """Выбор платёжного провайдера"""
    builder = InlineKeyboardBuilder()

    tbank_check = "✅ " if current_provider == "tbank" else ""
    crypto_check = "✅ " if current_provider == "cryptobot" else ""

    builder.button(
        text=f"{tbank_check}💳 Т-Банк",
        callback_data="topup_provider_tbank",
    )
    builder.button(
        text=f"{crypto_check}₿ Crypto Bot",
        callback_data="topup_provider_cryptobot",
    )
    builder.adjust(2)
    return builder.as_markup()


def get_payment_packages_keyboard(packages: list, provider: str = None):
    """Клавиатура выбора пакета бананов с выбором провайдера"""
    provider = provider or config.payment_provider
    if provider not in {"tbank", "cryptobot"}:
        provider = "tbank"

    builder = InlineKeyboardBuilder()
    provider_kb = get_payment_provider_keyboard(provider)
    if provider_kb.inline_keyboard:
        builder.row(*provider_kb.inline_keyboard[0])

    for pkg in packages:
        bonus = (
            f" +{pkg['bonus_credits']} бонусов (🍌)"
            if pkg.get("bonus_credits", 0) > 0
            else ""
        )
        builder.button(
            text=f"{pkg['credits']}🍌 - {pkg['price_rub']}₽{bonus}",
            callback_data=f"buy_{provider}_{pkg['id']}",
        )

    builder.button(text="🎟 Промокод", callback_data="promo_enter")
    builder.button(text="🔙 Назад", callback_data="menu_balance")
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


def get_image_result_keyboard(task_id: str, original_url: str = None):
    """Клавиатура для готового фото с кнопкой повтора"""
    builder = InlineKeyboardBuilder()
    if original_url:
        builder.button(text="📥 Скачать оригинал", url=original_url)
        builder.button(text="📸 Оживить фото", callback_data=f"animate_img_{task_id}")
        builder.button(text="📤 В ленту", callback_data=f"feed_publish_{task_id}")
    builder.button(text="🔄 Повторить", callback_data=f"retry_img_{task_id}")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    if original_url:
        builder.adjust(1, 2, 2)
    else:
        builder.adjust(2)
    return builder.as_markup()


def get_feed_card_keyboard(task_id: str, index: int = 0, is_owner: bool = False):
    """Клавиатура карточки bot-side ленты."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❤️", callback_data=f"feed_like_{task_id}_{index}")
    builder.button(text="📤", callback_data=f"feed_share_{task_id}")
    builder.button(text="➡️", callback_data=f"feed_next_{index + 1}")
    builder.button(text="🔁 Повторить", callback_data=f"feed_repeat_{task_id}")
    if is_owner:
        builder.button(text="🗑 Удалить из ленты", callback_data=f"feed_remove_{task_id}_{index}")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    if is_owner:
        builder.adjust(3, 1, 1, 1)
    else:
        builder.adjust(3, 1, 1)
    return builder.as_markup()


def get_feed_empty_keyboard():
    """Клавиатура пустого состояния ленты."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🖼 Создать фото", callback_data="create_image_refs_new")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def get_animate_photo_keyboard():
    """Клавиатура быстрых вариантов оживления готового фото."""
    builder = InlineKeyboardBuilder()
    presets = [
        ("😊 Улыбка", "smile"),
        ("👀 Моргнуть", "blink"),
        ("🎥 Приблизить камеру", "zoom"),
        ("🌪 Ветер в волосах", "wind"),
        ("🚶 Идти вперёд", "walk"),
        ("🗣 Говорить", "talk"),
        ("💃 Танцевать", "dance"),
        ("🎬 Свой вариант", "custom"),
    ]
    for text, preset in presets:
        builder.button(text=text, callback_data=f"animate_preset_{preset}")
    builder.button(text="⚙️ Модель и качество", callback_data="animate_settings")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def get_ai_assistant_keyboard():
    """Клавиатура для ИИ-ассистента"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 В главное меню", callback_data="back_main")
    return builder.as_markup()


def get_gpt55_keyboard():
    """Клавиатура GPT 5.5 чата"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🪄 Улучшить промпт", callback_data="gpt55_improve_prompt")
    builder.button(text="🧹 Очистить контекст", callback_data="gpt55_clear")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def get_prompt_improver_keyboard():
    """Клавиатура режима улучшения промпта."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔁 Еще раз", callback_data="gpt55_improve_again")
    builder.button(text="🧹 Очистить контекст", callback_data="gpt55_clear")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1, 1)
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
    builder.button(text="🍌 Использовать в боте", callback_data="partner_convert")
    builder.button(text="🎟️ Вывод заработка", callback_data="partner_withdraw")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1)
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
