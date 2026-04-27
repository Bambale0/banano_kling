import json
import logging
import os

from aiogram.types import InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.services.preset_manager import preset_manager

logger = logging.getLogger(__name__)


def load_prices():
    """Backward-compatible helper for tests and old integrations."""
    price_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "price.json",
    )
    with open(price_path, "r", encoding="utf-8") as f:
        return json.load(f)


try:
    PACKAGES = load_prices().get("packages", [])
except Exception:
    PACKAGES = []


# =============================================================================
# ГЛАВНОЕ МЕНЮ - согласно ux.md
# =============================================================================


def get_main_menu_keyboard(user_credits: int = 0):
    """Аккуратное главное меню: сценарии сверху, детали моделей внутри разделов."""
    builder = InlineKeyboardBuilder()

    if config.mini_app_url:
        builder.button(
            text="🚀 Открыть Mini App",
            web_app=WebAppInfo(url=config.mini_app_url),
        )
    builder.button(text="🖼 Создать фото", callback_data="create_image_text_new")
    builder.button(text="🎬 Создать видео", callback_data="create_video_new")
    builder.button(text="🎯 Motion Control", callback_data="motion_control")
    builder.button(text="📸 Промпт по фото", callback_data="photo_to_prompt")
    builder.button(text="📚 Промпт-канал", url="https://t.me/only_tm_ii")
    builder.button(text="🤖 AI-помощник", callback_data="menu_ai_assistant")
    builder.button(text=f"🍌 Баланс: {user_credits}", callback_data="menu_balance")
    builder.button(text="💬 Поддержка", callback_data="menu_support")
    builder.button(text="🤝 Партнёрам", callback_data="menu_partner")
    builder.button(text="⋯ Ещё", callback_data="ux_more")

    if config.mini_app_url:
        builder.adjust(1, 2, 2, 2, 2, 1, 1)
    else:
        builder.adjust(2, 2, 2, 2, 1, 1)

    return builder.as_markup()


def get_create_hub_keyboard():
    """Подменю создания: фото, видео и быстрые сценарии."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🖼 Фото", callback_data="create_image_text_new")
    builder.button(text="🎬 Видео", callback_data="create_video_new")
    builder.button(text="📱 Reels/TikTok", callback_data="quick_reels_video")
    builder.button(text="🛍 Товар/реклама", callback_data="quick_product_image")
    builder.button(text="⚡ Быстрый старт", callback_data="create_image_text_new")
    builder.button(text="⚙️ Свои настройки", callback_data="create_video_new")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def get_edit_hub_keyboard():
    """Подменю редактирования фото."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🎨 Сменить стиль", callback_data="edit_style_image")
    builder.button(text="🖼 Сменить фон", callback_data="edit_background_image")
    builder.button(text="🧩 По референсам", callback_data="create_image_refs_new")
    builder.button(text="🧠 Grok i2i", callback_data="edit_grok_i2i")
    builder.button(text="⚙️ Свои настройки", callback_data="create_image_refs_new")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def get_animate_hub_keyboard():
    """Подменю оживления фото и видео."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🖼 Фото → Видео", callback_data="quick_image_to_video")
    builder.button(text="🎯 Motion Control", callback_data="motion_control")
    builder.button(text="🎞 Видео-референс", callback_data="quick_video_reference")
    builder.button(text="🎬 Видео с нуля", callback_data="create_video_new")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1, 1, 1, 1)
    return builder.as_markup()


def get_motion_control_model_keyboard(current_model: str = "motion_control_v26"):
    """Отдельный выбор версии Motion Control."""
    builder = InlineKeyboardBuilder()

    options = [
        (
            "motion_control_v26",
            "🎯 Kling 2.6 Motion Control",
            "Стабильный перенос движения",
            preset_manager.get_video_cost("motion_control_v26", 5),
        ),
        (
            "motion_control_v30",
            "🚀 Kling 3.0 Motion Control",
            "Новая версия с улучшенной стабильностью",
            preset_manager.get_video_cost("motion_control_v30", 5),
        ),
    ]

    for model_key, title, description, cost in options:
        check = "✅ " if current_model == model_key else ""
        builder.row(
            InlineKeyboardButton(
                text=f"{check}{title} • {cost}🍌",
                callback_data=f"v_model_{model_key}",
            )
        )

    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main"))
    return builder.as_markup()


def get_more_menu_keyboard():
    """Вторичные разделы, чтобы не перегружать главный экран."""
    builder = InlineKeyboardBuilder()
    builder.button(text="💼 Партнёрам", callback_data="menu_partner")
    builder.button(text="📋 История", callback_data="menu_history")
    builder.button(text="❓ Как пользоваться", callback_data="menu_help")
    builder.button(text="💬 Поддержка", callback_data="menu_support")
    builder.button(text="💰 Пополнить", callback_data="menu_topup")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def get_admin_keyboard():
    """Админ-панель"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Перезагрузить пресеты", callback_data="admin_reload")
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="👥 Пользователи", callback_data="admin_users")
    builder.button(text="⚙️ Рассылка", callback_data="admin_broadcast")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


# =============================================================================
# МЕНЮ СОЗДАНИЯ ВИДЕО - всё на одном экране
# =============================================================================


SUPPORTED_RATIOS = {
    "v3_std": ["16:9", "9:16", "1:1"],
    "v3_pro": ["16:9", "9:16", "1:1"],
    "v26_pro": ["16:9", "9:16", "1:1"],
    "v3_omni_std": ["16:9", "9:16", "1:1"],
    "v3_omni_pro": ["16:9", "9:16", "1:1"],
    "grok_imagine": ["16:9", "9:16", "1:1", "3:2", "2:3"],
    "motion_control_v26": ["motion"],
    "motion_control_v30": ["motion"],
    "glow": ["16:9", "9:16", "1:1"],
    "veo3": ["16:9", "9:16", "Auto"],
    "veo3_fast": ["16:9", "9:16", "Auto"],
    "veo3_lite": ["16:9", "9:16", "Auto"],
}

VIDEO_MODEL_LABELS = {
    "v3_std": "Kling v3",
    "v3_pro": "Kling 3.0",
    "v26_pro": "Kling 2.5 Turbo Pro",
    "avatar_std": "Kling AI Avatar Standard",
    "avatar_pro": "Kling AI Avatar Pro",
    "motion_control_v26": "Kling 2.6 Motion Control",
    "motion_control_v30": "Kling 3.0 Motion Control",
    "grok_imagine": "Grok Imagine",
    "glow": "Kling Glow",
    "veo3": "Veo 3.1 Quality",
    "veo3_fast": "Veo 3.1 Fast",
    "veo3_lite": "Veo 3.1 Lite",
}

IMAGE_MODEL_LABELS = {
    "flux_pro": "GPT Image 2",
    "banana_pro": "Nano Banana Pro",
    "banana_2": "Nano Banana 2",
    "seedream_edit": "Seedream 4.5",
    "grok_imagine_i2i": "Grok Imagine",
    "wan_27": "Wan 2.7 Pro",
    "nanobanana": "Nano Banana Pro",
}


def get_video_model_label(model: str) -> str:
    """Human-friendly label for video model keys."""
    return VIDEO_MODEL_LABELS.get(model, model)


def get_video_type_label(v_type: str) -> str:
    """Human-friendly label for video generation type."""
    mapping = {
        "text": "Текст -> Видео",
        "imgtxt": "Фото + Текст -> Видео",
        "video": "Видео + Текст -> Видео",
        "avatar": "Аватар + Аудио -> Видео",
        "motion": "Motion Control",
    }
    return mapping.get(v_type, v_type)


def get_image_model_label(model: str) -> str:
    """Human-friendly label for image model keys."""
    return IMAGE_MODEL_LABELS.get(model, model)


def get_video_model_selection_keyboard(current_model: str = "v3_pro"):
    """Первый шаг: отдельный выбор модели видео."""
    builder = InlineKeyboardBuilder()

    model_rows = [
        ("v3_pro", "💎 Kling 3.0", preset_manager.get_video_cost("v3_pro", 5)),
        ("v3_std", "⚡ Kling v3", preset_manager.get_video_cost("v3_std", 5)),
        ("v26_pro", "🌀 Kling 2.5 Turbo", preset_manager.get_video_cost("v26_pro", 5)),
        (
            "avatar_std",
            "🗣 Avatar Standard",
            preset_manager.get_video_cost("avatar_std", 5),
        ),
        (
            "avatar_pro",
            "🎙 Avatar Pro",
            preset_manager.get_video_cost("avatar_pro", 5),
        ),
        ("veo3", "🎥 Veo 3.1 Quality", preset_manager.get_video_cost("veo3", 6)),
        (
            "veo3_fast",
            "🚀 Veo 3.1 Fast",
            preset_manager.get_video_cost("veo3_fast", 6),
        ),
        (
            "veo3_lite",
            "🌿 Veo 3.1 Lite",
            preset_manager.get_video_cost("veo3_lite", 6),
        ),
        ("glow", "✨ Kling Glow", preset_manager.get_video_cost("glow", 5)),
    ]

    for model_key, label, cost in model_rows:
        check = "✅ " if current_model == model_key else ""
        builder.row(
            InlineKeyboardButton(
                text=f"{check}{label} • {cost}🍌",
                callback_data=f"v_model_{model_key}",
            )
        )

    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main"))
    return builder.as_markup()


def get_video_media_step_keyboard(
    current_v_type: str = "text",
    current_model: str = "v3_pro",
    has_start_image: bool = False,
    reference_image_count: int = 0,
    reference_video_count: int = 0,
    has_avatar_audio: bool = False,
):
    """Второй шаг: тип генерации и загрузка нужного медиа."""
    builder = InlineKeyboardBuilder()

    if current_v_type == "motion":
        image_status = "загружено" if has_start_image else "не загружено"
        video_status = "загружено" if reference_video_count else "не загружено"
        builder.button(text=f"🖼 Фото персонажа: {image_status}", callback_data="motion_upload_image")
        builder.button(text=f"🎬 Видео движения: {video_status}", callback_data="motion_upload_video")
        builder.button(text="▶️ К промпту", callback_data="video_media_continue")
        builder.button(text="🤖 Сменить модель", callback_data="video_change_model")
        builder.button(text="🏠 Главное меню", callback_data="back_main")
        builder.adjust(2, 1, 2)
        return builder.as_markup()

    if current_v_type == "avatar":
        image_status = "загружено" if has_start_image else "не загружено"
        audio_status = "загружено" if has_avatar_audio else "не загружено"
        builder.button(text=f"🖼 Аватар: {image_status}", callback_data="avatar_upload_image")
        builder.button(text=f"🎵 Аудио: {audio_status}", callback_data="avatar_upload_audio")
        builder.button(text="▶️ К промпту", callback_data="video_media_continue")
        builder.button(text="🤖 Сменить модель", callback_data="video_change_model")
        builder.button(text="🏠 Главное меню", callback_data="back_main")
        builder.adjust(2, 1, 2)
        return builder.as_markup()

    text_check = "✅ " if current_v_type == "text" else ""
    imgtxt_check = "✅ " if current_v_type == "imgtxt" else ""
    video_check = "✅ " if current_v_type == "video" else ""

    builder.button(text=f"{text_check}📝 Текст → Видео", callback_data="v_type_text")
    builder.button(
        text=f"{imgtxt_check}🖼 Фото + Текст → Видео", callback_data="v_type_imgtxt"
    )
    builder.button(
        text=f"{video_check}🎬 Видео + Текст → Видео", callback_data="v_type_video"
    )

    if current_v_type == "imgtxt":
        start_status = "загружено" if has_start_image else "не загружено"
        builder.button(
            text=f"📷 Стартовое фото: {start_status}", callback_data="ignore"
        )
        if reference_image_count > 0:
            builder.button(
                text=f"🧩 Доп. референсы: {reference_image_count}",
                callback_data="ignore",
            )
        builder.button(text="▶️ К настройкам", callback_data="video_media_continue")
    elif current_v_type == "video":
        builder.button(
            text=f"📹 Видео-референсы: {reference_video_count}/5",
            callback_data="ignore",
        )
        builder.button(text="⏭ Без видео-рефов", callback_data="video_media_skip")
        builder.button(text="▶️ К настройкам", callback_data="video_media_continue")
    else:
        builder.button(text="▶️ К настройкам", callback_data="video_media_continue")

    builder.button(text="🤖 Сменить модель", callback_data="video_change_model")
    builder.button(text="🏠 Главное меню", callback_data="back_main")

    if current_v_type == "imgtxt" and reference_image_count > 0:
        builder.adjust(1, 2, 1, 2)
    elif current_v_type == "video":
        builder.adjust(3, 1, 2, 2)
    else:
        builder.adjust(3, 1, 2)

    return builder.as_markup()


def get_create_video_keyboard(
    current_v_type: str = "text",
    current_model: str = "v3_std",
    current_ratio: str = "16:9",
    current_duration: int = 5,
    current_mode: str = "720p",
    current_orientation: str = "video",
    current_video_model: str = None,  # Алиас для обратной совместимости
    current_grok_mode: str = "normal",
    current_veo_generation_type: str = "TEXT_2_VIDEO",
    current_veo_translation: bool = True,
    current_veo_resolution: str = "720p",
    current_veo_seed: int = None,
    current_veo_watermark: str = "",
    current_kling_negative_prompt: str = "",
    current_kling_cfg_scale: float = 0.5,
):
    """Шаг настроек видео после выбора модели и медиа."""
    # Если передан current_video_model, используем его
    if current_video_model is not None:
        current_model = current_video_model

    builder = InlineKeyboardBuilder()
    builder.button(text="🤖 Сменить модель", callback_data="video_change_model")
    builder.button(text="🎞 Тип и медиа", callback_data="video_change_media")

    # Модели - цены из preset_manager (синхронно с списанием)
    v3_std_cost = preset_manager.get_video_cost("v3_std", current_duration)
    v3_pro_cost = preset_manager.get_video_cost("v3_pro", current_duration)
    grok_cost = preset_manager.get_video_cost("grok_imagine", current_duration)
    glow_cost = preset_manager.get_video_cost("glow", current_duration)
    veo_quality_cost = preset_manager.get_video_cost("veo3", current_duration)
    veo_fast_cost = preset_manager.get_video_cost("veo3_fast", current_duration)
    veo_lite_cost = preset_manager.get_video_cost("veo3_lite", current_duration)

    ratio_buttons = []
    available_durations = []
    if current_model not in {"avatar_std", "avatar_pro"}:
        supported_ratios = SUPPORTED_RATIOS.get(current_model, ["16:9", "9:16", "1:1"])
        for ratio in supported_ratios:
            check = "✅ " if current_ratio == ratio else ""
            label = ratio.replace(":", "∶")  # визуально лучше
            ratio_buttons.append(
                InlineKeyboardButton(
                    text=f"{check}{label}",
                    callback_data=f"ratio_{ratio.replace(':', '_')}",
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
        if current_model.startswith("veo3"):
            available_durations = [2, 4, 6, 8, 10]
        elif duration_costs:
            available_durations = sorted([int(k) for k in duration_costs.keys()])
        else:
            available_durations = [5, 10, 15]

        show_durations = True
        for dur in available_durations:
            check = "✅ " if current_duration == dur else ""
            builder.button(text=f"{check}{dur} сек", callback_data=f"video_dur_{dur}")
    else:
        show_durations = False

    # Grok Imagine modes
    if current_model == "grok_imagine":
        normal_check = "✅ " if current_grok_mode == "normal" else ""
        fun_check = "✅ " if current_grok_mode == "fun" else ""
        spicy_check = "✅ " if current_grok_mode == "spicy" else ""
        builder.button(text=f"{normal_check}Normal", callback_data="grok_mode_normal")
        builder.button(text=f"{fun_check}Fun 🎉", callback_data="grok_mode_fun")
        builder.button(text=f"{spicy_check}Spicy 🔥", callback_data="grok_mode_spicy")

    if current_model.startswith("veo3"):
        translate_check = "✅ " if current_veo_translation else ""
        builder.button(
            text=f"{translate_check}🌐 Перевод промпта",
            callback_data="veo_translation_toggle",
        )

        if current_v_type == "imgtxt":
            frames_check = (
                "✅ "
                if current_veo_generation_type == "FIRST_AND_LAST_FRAMES_2_VIDEO"
                else ""
            )
            builder.button(
                text=f"{frames_check}🎞 Кадры",
                callback_data="veo_gen_FIRST_AND_LAST_FRAMES_2_VIDEO",
            )
            if current_model == "veo3_fast":
                refs_check = (
                    "✅ " if current_veo_generation_type == "REFERENCE_2_VIDEO" else ""
                )
                builder.button(
                    text=f"{refs_check}🧩 Референсы",
                    callback_data="veo_gen_REFERENCE_2_VIDEO",
                )

        for resolution in ("720p", "1080p", "4k"):
            check = "✅ " if current_veo_resolution == resolution else ""
            label = resolution.upper() if resolution == "4k" else resolution
            builder.button(
                text=f"{check}🖥 {label}",
                callback_data=f"veo_resolution_{resolution}",
            )

        seed_label = str(current_veo_seed) if current_veo_seed is not None else "auto"
        watermark_label = "off" if not current_veo_watermark else "on"
        builder.button(text=f"🎲 Seed: {seed_label}", callback_data="veo_seed_edit")
        builder.button(
            text=f"🏷 Watermark: {watermark_label}",
            callback_data="veo_watermark_edit",
        )

    if current_model == "v26_pro":
        negative_label = (
            current_kling_negative_prompt[:24] + "..."
            if current_kling_negative_prompt and len(current_kling_negative_prompt) > 24
            else (current_kling_negative_prompt or "off")
        )
        builder.button(
            text=f"🚫 Negative: {negative_label}",
            callback_data="kling_negative_prompt_edit",
        )
        builder.button(
            text=f"🎚 CFG: {current_kling_cfg_scale:.1f}",
            callback_data="kling_cfg_scale_edit",
        )

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
    builder.button(text=f"Стоимость: {total_cost}🍌", callback_data="ignore")
    builder.button(text="🏠 Главное меню", callback_data="back_main")

    widths = [2]
    if ratio_buttons:
        widths.append(len(ratio_buttons))
    if show_durations and available_durations:
        widths.append(len(available_durations))
    grok_width = 3 if current_model == "grok_imagine" else 0
    if current_v_type == "video":
        widths += [4, 2]
    if grok_width:
        widths += [grok_width]
    if current_model.startswith("veo3"):
        widths += [1]
        if current_v_type == "imgtxt":
            widths += [2 if current_model == "veo3_fast" else 1]
        widths += [3, 2]
    if current_model == "v26_pro":
        widths += [2]
    widths += [2]
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
# ВЫБОР МОДЕЛИ ДЛЯ ФОТО
# =============================================================================


def get_image_model_selection_keyboard(current_service: str = "banana_pro"):
    """Первый шаг: отдельный выбор модели фото."""
    builder = InlineKeyboardBuilder()

    model_rows = [
        (
            "banana_pro",
            "model_banana_pro",
            "💎 Nano Banana Pro",
            preset_manager.get_generation_cost("nano-banana-pro"),
        ),
        (
            "banana_2",
            "model_banana_2",
            "🍌 Nano Banana 2",
            preset_manager.get_generation_cost("banana_2"),
        ),
        (
            "seedream_edit",
            "model_seedream_edit",
            "🖌 Seedream 4.5",
            preset_manager.get_generation_cost("seedream_edit"),
        ),
        (
            "grok_imagine_i2i",
            "model_grok_i2i",
            "🧠 Grok Imagine",
            preset_manager.get_generation_cost("grok_imagine_i2i"),
        ),
        (
            "wan_27",
            "model_wan_27",
            "🧪 Wan 2.7 Pro",
            preset_manager.get_generation_cost("wan_27"),
        ),
        (
            "flux_pro",
            "model_flux_pro",
            "🧩 GPT Image 2",
            preset_manager.get_generation_cost("flux_pro"),
        ),
    ]

    for model_key, callback_data, label, cost in model_rows:
        check = "✅ " if current_service == model_key else ""
        builder.row(
            InlineKeyboardButton(
                text=f"{check}{label} • {cost}🍌",
                callback_data=callback_data,
            )
        )

    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main"))
    return builder.as_markup()


# =============================================================================
# МЕНЮ СОЗДАНИЯ ФОТО - всё на одном экране
# =============================================================================


def get_create_image_keyboard(
    current_service: str = "banana_pro",
    current_ratio: str = "1:1",
    current_count: int = 1,
    num_refs: int = 0,
    nsfw_enabled: bool = False,
    img_quality: str = "basic",
    img_nsfw_checker: bool = False,
):
    """Шаг настроек фото после выбора модели и референсов."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🤖 Сменить модель", callback_data="image_change_model"
        )
    )

    # Размер
    supported_ratios = (
        ["auto", "1:1", "9:16", "16:9", "4:3", "3:4"]
        if current_service == "flux_pro"
        else (
            ["1:1", "4:3", "3:4", "16:9", "9:16", "2:3", "3:2", "21:9"]
            if current_service == "seedream_edit"
            else ["1:1", "16:9", "9:16", "4:3", "3:2"]
        )
    )
    ratio_buttons = []
    for ratio in supported_ratios:
        marker = "◉" if current_ratio == ratio else "○"
        label = ratio.replace(":", "∶")
        ratio_buttons.append(
            InlineKeyboardButton(
                text=f"{marker} {label}",
                callback_data=f"img_ratio_{ratio.replace(':', '_')}",
            )
        )
    if len(ratio_buttons) <= 3:
        builder.row(*ratio_buttons)
    elif len(ratio_buttons) <= 5:
        builder.row(*ratio_buttons[:3])
        builder.row(*ratio_buttons[3:])
    else:
        builder.row(*ratio_buttons[:3])
        builder.row(*ratio_buttons[3:6])
        builder.row(*ratio_buttons[6:])

    count_buttons = []
    for count in [1, 2, 4, 6]:
        marker = "◉" if current_count == count else "○"
        count_buttons.append(
            InlineKeyboardButton(
                text=f"{marker} {count}x",
                callback_data=f"img_count_{count}",
            )
        )
    builder.row(*count_buttons[:2])
    builder.row(*count_buttons[2:])

    if current_service == "seedream_edit":
        basic_marker = "◉" if img_quality == "basic" else "○"
        high_marker = "◉" if img_quality == "high" else "○"
        seedream_nsfw_text = (
            "🔞 NSFW checker: on" if img_nsfw_checker else "🛡 NSFW checker: off"
        )
        builder.row(
            InlineKeyboardButton(
                text=f"{basic_marker} Basic 2K",
                callback_data="img_quality_basic",
            ),
            InlineKeyboardButton(
                text=f"{high_marker} High 4K",
                callback_data="img_quality_high",
            ),
        )
        builder.row(
            InlineKeyboardButton(
                text=seedream_nsfw_text,
                callback_data="seedream_nsfw_toggle",
            )
        )

    if current_service == "flux_pro":
        gpt_nsfw_text = (
            "🔞 NSFW checker: on" if img_nsfw_checker else "🛡 NSFW checker: off"
        )
        builder.row(
            InlineKeyboardButton(
                text=gpt_nsfw_text,
                callback_data="gpt_nsfw_toggle",
            )
        )

    if current_service == "grok_imagine_i2i":
        nsfw_text = "🔓 NSFW Вкл" if nsfw_enabled else "🔒 NSFW Выкл"
        builder.row(
            InlineKeyboardButton(text=nsfw_text, callback_data="grok_i2i_nsfw_toggle")
        )

    # Main menu button
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main"))

    return builder.as_markup()


# =============================================================================
# МЕНЮ ПОПОЛНЕНИЯ
# =============================================================================


def get_topup_keyboard():
    """Меню пополнения баланса"""
    return get_payment_packages_keyboard(preset_manager.get_packages())


def get_payment_packages_keyboard(packages: list):
    """Клавиатура выбора пакета бананов (CryptoBot)."""
    builder = InlineKeyboardBuilder()

    for pkg in packages:
        popular = " 🔥" if pkg.get("popular") else ""
        builder.button(
            text=f"{pkg['name']}: {pkg['credits']}🍌 за {pkg['price_rub']}₽{popular}",
            callback_data=f"buy_crypto_{pkg['id']}",
        )

    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def get_payment_provider_keyboard():
    """Совместимость со старым меню выбора провайдера оплаты."""
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 CryptoBot", callback_data="menu_topup")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1)
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
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 2)
    return builder.as_markup()


def get_main_menu_button_keyboard():
    """Одна кнопка возврата в главное меню."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    return builder.as_markup()


def get_back_keyboard(callback_data: str = "back_main"):
    """Кнопка назад с быстрым возвратом в главное меню."""
    builder = InlineKeyboardBuilder()
    if callback_data == "back_main":
        builder.button(text="🏠 Главное меню", callback_data="back_main")
        builder.adjust(1)
        return builder.as_markup()
    builder.button(text="🔙 Назад", callback_data=callback_data)
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2)
    return builder.as_markup()


def get_confirm_keyboard(confirm_data: str, cancel_data: str):
    """Клавиатура подтверждения действия"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=confirm_data)
    builder.button(text="❌ Отмена", callback_data=cancel_data)
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 1)
    return builder.as_markup()


def get_video_result_keyboard(
    video_url: str, user_credits: int = 0, task_id: str = None, model: str = None
):
    """Клавиатура для готового видео"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📥 Скачать видео", url=video_url)
    if task_id and model and model.startswith("veo3"):
        builder.button(text="✨ Получить 1080p", callback_data=f"veo1080_{task_id}")
        builder.button(text="🖥 Получить 4K", callback_data=f"veo4k_{task_id}")
        builder.button(text="➕ Продлить", callback_data=f"veoextend_{task_id}")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    if task_id and model and model.startswith("veo3"):
        builder.adjust(1, 2, 1, 1)
    else:
        builder.adjust(1)
    return builder.as_markup()


def get_image_result_keyboard(image_url: str, task_id: str = None):
    """Клавиатура для готового фото."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📥 Скачать оригинал", url=image_url)
    if task_id:
        builder.button(text="🔁 Повторить", callback_data=f"repeat_image_{task_id}")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 2)
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
    builder.button(text="🏠 Главное меню", callback_data="back_main")
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
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 1, 1)
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
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 2)
    return builder.as_markup()


def get_aspect_ratio_keyboard(preset_id: str, current_ratio: str = "16:9"):
    """Клавиатура выбора формата"""
    builder = InlineKeyboardBuilder()
    for ratio, label in [("16:9", "📺"), ("9:16", "📱"), ("1:1", "⬜")]:
        emoji = "✅ " if ratio == current_ratio else ""
        builder.button(
            text=f"{emoji}{label} {ratio.replace(':', '∶')}",
            callback_data=f"ratio_{preset_id}_{ratio}",
        )
    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(3, 2)
    return builder.as_markup()


def get_image_aspect_ratio_keyboard(preset_id: str, current_ratio: str = "1:1"):
    """Клавиатура выбора формата изображения"""
    builder = InlineKeyboardBuilder()
    for ratio, label in [
        ("1:1", "⬜"),
        ("16:9", "📺"),
        ("9:16", "📱"),
        ("4:5", "🖼"),
        ("21:9", "🎬"),
    ]:
        emoji = "✅ " if ratio == current_ratio else ""
        builder.button(
            text=f"{emoji}{label} {ratio.replace(':', '∶')}",
            callback_data=f"img_ratio_{preset_id}_{ratio}",
        )
    builder.button(text="🔙 Назад", callback_data=f"model_{preset_id}")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(3, 2, 2)
    return builder.as_markup()


def get_advanced_options_keyboard():
    """Клавиатура расширенных опций (заглушка для исправления импорта)"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()
