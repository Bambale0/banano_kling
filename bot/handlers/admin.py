import json
import logging
import html as html_utils
from datetime import datetime
from pathlib import Path

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramAPIError, TelegramEntityTooLarge
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile

from bot.config import config
from bot.database import (
    add_credits,
    deduct_credits,
    get_admin_finance_report,
    get_admin_partner_details,
    get_admin_partner_stats,
    get_admin_stats,
    get_partner_withdrawal_request,
    get_pending_partner_withdrawals,
    get_user_stats,
)
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
BROADCAST_MESSAGE_LIMIT = 4096
BROADCAST_PHOTO_CAPTION_LIMIT = 1024
ADMIN_FINANCE_PREVIEW_LIMIT = 25
ADMIN_FINANCE_XLS_LIMIT = 5000
ADMIN_FINANCE_XLS_FALLBACK_LIMIT = 1000
ADMIN_FINANCE_TELEGRAM_MAX_BYTES = 45 * 1024 * 1024
ADMIN_FINANCE_LONG_CELL_LIMITS = {
    "prompt": 1200,
    "request_data": 1500,
    "requisites": 1200,
    "result_url": 800,
}

ADMIN_FINANCE_SECTION_ORDER = [
    "topups",
    "deductions",
    "referrals_l1",
    "referrals_l2",
    "partner_commissions",
    "withdrawals",
]
ADMIN_FINANCE_SECTION_TITLES = {
    "topups": "Пополнения",
    "deductions": "Списания",
    "referrals_l1": "Рефералы 1 линии",
    "referrals_l2": "Рефералы 2 линии",
    "partner_commissions": "Партнёрские начисления",
    "withdrawals": "Выводы партнёров",
}
ADMIN_FINANCE_COLUMNS = {
    "topups": [
        ("id", "ID"),
        ("created_at", "Дата"),
        ("telegram_id", "Telegram ID"),
        ("user_db_id", "User DB ID"),
        ("credits", "Бананы"),
        ("amount_rub", "Сумма, ₽"),
        ("status", "Статус"),
        ("provider", "Провайдер"),
        ("order_id", "Order ID"),
        ("payment_id", "Payment ID"),
        ("user_balance", "Баланс после/текущий"),
        ("referrer_telegram_id", "Реферер Telegram ID"),
        ("referrer_code", "Код реферера"),
        ("referral_code", "Код пользователя"),
    ],
    "deductions": [
        ("source", "Источник"),
        ("id", "ID"),
        ("created_at", "Дата"),
        ("telegram_id", "Telegram ID"),
        ("user_db_id", "User DB ID"),
        ("cost", "Списано, 🍌"),
        ("status", "Статус"),
        ("task_id", "Task/Job ID"),
        ("type", "Тип"),
        ("preset_id", "Preset"),
        ("model", "Модель"),
        ("duration", "Длительность"),
        ("aspect_ratio", "Формат"),
        ("results_count", "Результатов"),
        ("prompt", "Промпт"),
        ("result_url", "Результат"),
        ("request_data", "Request data"),
        ("completed_at", "Завершено"),
        ("updated_at", "Обновлено"),
        ("user_balance", "Текущий баланс"),
        ("referrer_telegram_id", "Реферер Telegram ID"),
        ("referrer_code", "Код реферера"),
    ],
    "referrals_l1": [
        ("id", "Referral ID"),
        ("referral_created_at", "Дата привязки"),
        ("referrer_telegram_id", "Партнёр L1 Telegram ID"),
        ("referrer_user_id", "Партнёр L1 DB ID"),
        ("referrer_code", "Код партнёра"),
        ("referrer_tier", "Тир партнёра"),
        ("referrer_balance_rub", "Баланс партнёра, ₽"),
        ("referrer_total_revenue_rub", "Оборот партнёра, ₽"),
        ("referred_telegram_id", "Реферал Telegram ID"),
        ("referred_user_id", "Реферал DB ID"),
        ("referred_code", "Код реферала"),
        ("referred_created_at", "Дата регистрации"),
        ("referred_balance", "Баланс реферала"),
        ("referred_has_paid", "Оплачивал"),
        ("payments_count", "Оплат"),
        ("paid_rub", "Оплачено, ₽"),
        ("paid_credits", "Куплено 🍌"),
        ("last_payment_at", "Последняя оплата"),
        ("subrefs_count", "Рефералов 2 линии"),
        ("bonus_credits", "Бонус пригласившему, 🍌"),
    ],
    "referrals_l2": [
        ("root_partner_telegram_id", "Корневой партнёр Telegram ID"),
        ("root_partner_user_id", "Корневой партнёр DB ID"),
        ("root_partner_code", "Код корневого партнёра"),
        ("root_partner_tier", "Тир корневого партнёра"),
        ("line1_telegram_id", "Партнёр 1 линии Telegram ID"),
        ("line1_user_id", "Партнёр 1 линии DB ID"),
        ("line1_code", "Код партнёра 1 линии"),
        ("line1_created_at", "Дата регистрации 1 линии"),
        ("line2_telegram_id", "Реферал 2 линии Telegram ID"),
        ("line2_user_id", "Реферал 2 линии DB ID"),
        ("line2_code", "Код реферала 2 линии"),
        ("line2_created_at", "Дата регистрации 2 линии"),
        ("line2_balance", "Баланс 2 линии"),
        ("line2_has_paid", "Оплачивал"),
        ("referral_created_at", "Дата привязки"),
        ("payments_count", "Оплат"),
        ("paid_rub", "Оплачено, ₽"),
        ("paid_credits", "Куплено 🍌"),
        ("last_payment_at", "Последняя оплата"),
        ("bonus_credits", "Бонус, 🍌"),
    ],
    "partner_commissions": [
        ("transaction_id", "Transaction ID"),
        ("created_at", "Дата оплаты"),
        ("order_id", "Order ID"),
        ("provider", "Провайдер"),
        ("payer_telegram_id", "Плательщик Telegram ID"),
        ("payer_user_id", "Плательщик DB ID"),
        ("payer_code", "Код плательщика"),
        ("credits", "Куплено 🍌"),
        ("amount_rub", "Сумма оплаты, ₽"),
        ("level1_partner_telegram_id", "Партнёр L1 Telegram ID"),
        ("level1_partner_user_id", "Партнёр L1 DB ID"),
        ("level1_partner_code", "Код партнёра L1"),
        ("level1_partner_tier", "Тир партнёра L1"),
        ("level1_percent", "Процент L1"),
        ("level1_commission_rub", "Начисление L1, ₽"),
        ("level2_partner_telegram_id", "Партнёр L2 Telegram ID"),
        ("level2_partner_user_id", "Партнёр L2 DB ID"),
        ("level2_partner_code", "Код партнёра L2"),
        ("level2_partner_tier", "Тир партнёра L2"),
        ("level2_percent", "Процент L2"),
        ("level2_commission_rub", "Начисление L2, ₽"),
    ],
    "withdrawals": [
        ("id", "ID заявки"),
        ("created_at", "Создана"),
        ("updated_at", "Обновлена"),
        ("telegram_id", "Telegram ID"),
        ("user_db_id", "User DB ID"),
        ("amount_rub", "Сумма, ₽"),
        ("status", "Статус"),
        ("method", "Метод"),
        ("requisites", "Реквизиты"),
        ("current_balance_rub", "Текущий баланс, ₽"),
        ("withdrawn_rub", "Выведено всего, ₽"),
        ("total_revenue_rub", "Партнёрский оборот, ₽"),
    ],
}


def _broadcast_confirm_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="✅ Отправить", callback_data="admin_broadcast_confirm"
                ),
                types.InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back"),
            ]
        ]
    )


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


def _admin_finance_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="📥 Пополнения", callback_data="admin_finance_topups"
                ),
                types.InlineKeyboardButton(
                    text="🍌 Списания", callback_data="admin_finance_deductions"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="🤝 1 линия", callback_data="admin_finance_referrals_l1"
                ),
                types.InlineKeyboardButton(
                    text="🧬 2 линия", callback_data="admin_finance_referrals_l2"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="💰 Начисления",
                    callback_data="admin_finance_partner_commissions",
                ),
                types.InlineKeyboardButton(
                    text="🏦 Выводы", callback_data="admin_finance_withdrawals"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="📤 XLS весь отчёт", callback_data="admin_finance_xls_all"
                )
            ],
            [types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
        ]
    )


def _admin_finance_section_keyboard(section: str) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="📤 XLS раздела",
                    callback_data=f"admin_finance_xls_{section}",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔙 К отчёту", callback_data="admin_finance"
                ),
                types.InlineKeyboardButton(
                    text="🏠 Админка", callback_data="admin_back"
                ),
            ],
        ]
    )


def _admin_partners_keyboard(top_partners: list[dict]) -> types.InlineKeyboardMarkup:
    rows: list[list[types.InlineKeyboardButton]] = [
        [
            types.InlineKeyboardButton(
                text="💸 Заявки на вывод",
                callback_data="admin_partner_withdrawals",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="🔎 Открыть по Telegram ID",
                callback_data="admin_partner_lookup",
            )
        ]
    ]

    for partner in top_partners[:8]:
        rows.append(
            [
                types.InlineKeyboardButton(
                    text=(
                        f"ID {partner['telegram_id']} • "
                        f"{partner['balance_rub']:.0f}₽ • "
                        f"{partner['level1_count']} реф."
                    ),
                    callback_data=f"admin_partner_view_{partner['telegram_id']}",
                )
            ]
        )

    rows.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_partner_detail_keyboard(telegram_id: int) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🔄 Обновить",
                    callback_data=f"admin_partner_view_{telegram_id}",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔎 Открыть другого", callback_data="admin_partner_lookup"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔙 К партнёрам", callback_data="admin_partners"
                )
            ],
        ]
    )


def _admin_withdrawals_keyboard(withdrawals: list[dict]) -> types.InlineKeyboardMarkup:
    rows: list[list[types.InlineKeyboardButton]] = []
    for item in withdrawals[:12]:
        rows.append(
            [
                types.InlineKeyboardButton(
                    text=(
                        f"#{item['id']} • ID {item['telegram_id']} • "
                        f"{item['amount_rub']:.0f}₽"
                    ),
                    callback_data=f"admin_partner_withdrawal_{item['id']}",
                )
            ]
        )

    rows.append(
        [types.InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_partner_withdrawals")]
    )
    rows.append([types.InlineKeyboardButton(text="🔙 К партнёрам", callback_data="admin_partners")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_withdrawal_detail_keyboard(withdrawal_id: int) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"partner_withdraw_approve_{withdrawal_id}",
                ),
                types.InlineKeyboardButton(
                    text="❌ Отменить",
                    callback_data=f"partner_withdraw_cancel_{withdrawal_id}",
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="🔄 Обновить",
                    callback_data=f"admin_partner_withdrawal_{withdrawal_id}",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔙 К заявкам", callback_data="admin_partner_withdrawals"
                )
            ],
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


VIDEO_MODEL_LABELS = {
    "v3_std": "Kling v3 Std",
    "v3_pro": "Kling 3.0 Pro",
    "v26_pro": "Kling 2.5 Turbo",
    "v26_motion_pro": "Motion Pro",
    "motion_control_v26": "Motion Control 2.6",
    "motion_control_v30": "Motion Control 3.0",
    "grok_imagine": "Grok Imagine",
    "veo3": "Veo 3.1 Quality",
    "veo3_fast": "Veo 3.1 Fast",
    "veo3_lite": "Veo 3.1 Lite",
    "gemini_omni_video": "Gemini Omni Video",
    "gemini_omni_audio": "Gemini Omni Audio",
    "gemini_omni_character": "Gemini Omni Character",
    "glow": "Kling Glow",
}


def _model_per_sec(model_cfg: dict) -> str:
    """Возвращает строку 'X🍌/с' для модели."""
    def _format_per_sec(value: float) -> str:
        return f"{value:.2f}".rstrip("0").rstrip(".")

    quality_costs = (model_cfg or {}).get("quality_costs", {})
    if quality_costs:
        values = [float(value) for value in quality_costs.values()]
        if not values:
            return "?"
        min_value = min(values)
        max_value = max(values)
        if min_value == max_value:
            return _format_per_sec(min_value)
        return f"{_format_per_sec(min_value)}-{_format_per_sec(max_value)}"

    duration_costs = (model_cfg or {}).get("duration_costs", {})
    if duration_costs:
        ref_dur = 5 if "5" in duration_costs else int(min(duration_costs, key=int))
        cost = duration_costs[str(ref_dur)]
        per_sec = cost / ref_dur
        return _format_per_sec(per_sec)
    base = (model_cfg or {}).get("base", (model_cfg or {}).get("cost"))
    return str(base) if base is not None else "?"


def _admin_video_prices_keyboard() -> types.InlineKeyboardMarkup:
    """Одна кнопка на модель с отображением цены за секунду."""
    video_models = (
        preset_manager.get_price_config()
        .get("costs_reference", {})
        .get("video_models", {})
    )
    buttons = []
    for model_key, model_cfg in video_models.items():
        per_sec = _model_per_sec(model_cfg)
        label = VIDEO_MODEL_LABELS.get(model_key, model_key)
        buttons.append(
            types.InlineKeyboardButton(
                text=f"{label} • {per_sec}🍌/с",
                callback_data=f"admin_video_model_{model_key}",
            )
        )
    rows = _chunk_buttons(buttons, 1) + [
        [types.InlineKeyboardButton(text="🔙 К разделам", callback_data="admin_prices")]
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_video_model_keyboard(model_key: str) -> types.InlineKeyboardMarkup:
    """Детальный экран модели: каждая длительность + кнопка 'цена за 1с'."""
    video_models = (
        preset_manager.get_price_config()
        .get("costs_reference", {})
        .get("video_models", {})
    )
    model_cfg = video_models.get(model_key, {})
    quality_costs = model_cfg.get("quality_costs", {})
    duration_costs = model_cfg.get("duration_costs", {})
    quality_order = {"720p": 0, "1080p": 1, "4k": 2}

    buttons = []
    if quality_costs:
        for quality in sorted(
            quality_costs.keys(),
            key=lambda q: (quality_order.get(str(q).lower(), 99), str(q)),
        ):
            cost = quality_costs[quality]
            buttons.append(
                types.InlineKeyboardButton(
                    text=f"{quality} → {cost}🍌/с",
                    callback_data=f"admin_price_video_{model_key}_q{quality}",
                )
            )
    elif duration_costs:
        for dur_str, cost in sorted(duration_costs.items(), key=lambda x: int(x[0])):
            buttons.append(
                types.InlineKeyboardButton(
                    text=f"{dur_str}с → {cost}🍌",
                    callback_data=f"admin_price_video_{model_key}_{dur_str}",
                )
            )
        buttons.append(
            types.InlineKeyboardButton(
                text="⚡ Установить цену за 1с (пересчёт всех)",
                callback_data=f"admin_price_video_{model_key}_persec",
            )
        )
    else:
        base = model_cfg.get("base", model_cfg.get("cost"))
        buttons.append(
            types.InlineKeyboardButton(
                text=f"Базовая цена → {base}🍌",
                callback_data=f"admin_price_video_{model_key}_base",
            )
        )

    rows = _chunk_buttons(buttons, 2) + [
        [
            types.InlineKeyboardButton(
                text="🔙 К моделям", callback_data="admin_prices_videos"
            )
        ]
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
        if field == "persec":
            # Пересчитываем все длительности по новой цене за секунду
            per_sec = float(value)
            duration_costs = model.get("duration_costs", {})
            if duration_costs:
                old_ref_dur = (
                    5 if "5" in duration_costs else int(min(duration_costs, key=int))
                )
                old_value = round(duration_costs[str(old_ref_dur)] / old_ref_dur, 2)
                new_durations = {}
                for dur_str in duration_costs:
                    new_durations[dur_str] = round(per_sec * int(dur_str))
                model["duration_costs"] = new_durations
                ref_dur = (
                    5 if "5" in new_durations else int(min(new_durations, key=int))
                )
                model["base"] = new_durations[str(ref_dur)]
            else:
                old_value = model.get("base", model.get("cost", 0))
                model["base"] = round(per_sec * 5)
        elif field == "base":
            target_key = "base" if "base" in model else "cost"
            old_value = model[target_key]
            model[target_key] = value
        elif field.startswith("q"):
            quality = field[1:]
            quality_costs = model.get("quality_costs")
            if not quality_costs or quality not in quality_costs:
                raise KeyError("video_quality")
            old_value = quality_costs[quality]
            quality_costs[quality] = value
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


def _format_admin_partners_text(stats: dict) -> str:
    lines = [
        "🤝 <b>Партнёрская статистика</b>",
        "",
        f"• Партнёров всего: <code>{stats['total_partners']}</code>",
        f"• Активных партнёров: <code>{stats['active_partners']}</code>",
        f"• На балансах: <code>{stats['total_balance_rub']:.2f}</code> ₽",
        f"• Выведено: <code>{stats['total_withdrawn_rub']:.2f}</code> ₽",
        f"• Оборот рефералок: <code>{stats['total_partner_revenue_rub']:.2f}</code> ₽",
        "",
        "<b>Топ партнёров:</b>",
    ]

    top_partners = stats.get("top_partners") or []
    if not top_partners:
        lines.append("• Пока нет данных")
    else:
        for index, partner in enumerate(top_partners[:5], start=1):
            lines.append(
                f"{index}. <code>{partner['telegram_id']}</code> "
                f"• {partner['level1_count']} / {partner['level2_count']} реф. "
                f"• баланс <code>{partner['balance_rub']:.2f}</code> ₽"
            )

    lines.extend(["", "Можно открыть карточку партнёра по кнопке или ввести Telegram ID."])
    return "\n".join(lines)


def _format_admin_partner_details_text(details: dict) -> str:
    overview = details["overview"]
    lines = [
        "👤 <b>Карточка партнёра</b>",
        "",
        f"🆔 Telegram ID: <code>{details['telegram_id']}</code>",
        f"🔗 Рефкод: <code>{details.get('referral_code') or '—'}</code>",
        f"🍌 Баланс пользователя: <code>{details['credits']}</code>",
        f"🤝 Активировал партнёрку: <code>{'да' if details['is_partner'] else 'нет'}</code>",
        f"📅 Активирована: <code>{details.get('partner_agreed_at') or '—'}</code>",
        "",
        "<b>Показатели:</b>",
        f"• 1 уровень: <code>{overview.get('level1_count', 0)}</code>",
        f"• 2 уровень: <code>{overview.get('level2_count', 0)}</code>",
        f"• Баланс к выводу: <code>{overview.get('balance_rub', 0):.2f}</code> ₽",
        f"• Выведено: <code>{overview.get('withdrawn_rub', 0):.2f}</code> ₽",
        f"• Оборот: <code>{overview.get('total_revenue_rub', 0):.2f}</code> ₽",
        f"• Оплат по 1 уровню: <code>{overview.get('total_payments', 0)}</code>",
        f"• Выручка по оплатам 1 уровня: <code>{overview.get('monthly_revenue', 0):.2f}</code> ₽",
        f"• Активных за 7 дней: <code>{overview.get('active_7d', 0)}</code>",
        "",
        "<b>Прямые рефералы:</b>",
    ]

    referrals = details.get("referrals") or []
    if not referrals:
        lines.append("• Нет прямых рефералов")
    else:
        for ref in referrals:
            paid_label = "платил" if ref["has_paid"] else "без оплат"
            lines.append(
                f"• <code>{ref['telegram_id']}</code> "
                f"({paid_label}, {ref['payments_count']} оплат) "
                f"• потратил <code>{ref['spent_rub']:.2f}</code> ₽ "
                f"• 🍌 <code>{ref['credits']}</code> "
                f"• привёл <code>{ref['subrefs_count']}</code>"
            )

    return "\n".join(lines)


def _format_admin_withdrawals_text(withdrawals: list[dict]) -> str:
    lines = [
        "💸 <b>Заявки на вывод</b>",
        "",
        f"• Ожидают обработки: <code>{len(withdrawals)}</code>",
        "",
    ]

    if not withdrawals:
        lines.append("• Сейчас нет ожидающих заявок")
    else:
        for item in withdrawals[:12]:
            lines.append(
                f"• <code>#{item['id']}</code> "
                f"ID <code>{item['telegram_id']}</code> "
                f"— <code>{item['amount_rub']:.2f}</code> ₽ "
                f"(баланс <code>{item['current_balance_rub']:.2f}</code> ₽)"
            )

    return "\n".join(lines)


def _format_admin_withdrawal_detail_text(withdrawal: dict) -> str:
    return "\n".join(
        [
            "💸 <b>Заявка на вывод</b>",
            "",
            f"ID заявки: <code>{withdrawal['id']}</code>",
            f"Telegram ID: <code>{withdrawal['telegram_id']}</code>",
            f"Статус: <code>{withdrawal['status']}</code>",
            f"Сумма: <code>{withdrawal['amount_rub']:.2f}</code> ₽",
            f"Фактический баланс: <code>{withdrawal['current_balance_rub']:.2f}</code> ₽",
            f"Создана: <code>{withdrawal['created_at']}</code>",
            "",
            "Реквизиты:",
            f"<code>{withdrawal['requisites'] or '—'}</code>",
        ]
    )


def _html(value) -> str:
    return html_utils.escape("" if value is None else str(value))


def _code(value) -> str:
    text = "—" if value is None or value == "" else value
    return f"<code>{_html(text)}</code>"


def _short(value, limit: int = 72) -> str:
    if value is None or value == "":
        return "—"
    text = str(value).replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _as_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _money(value) -> str:
    return f"{_as_float(value):.2f}"


def _admin_finance_total_for_section(section: str, summary: dict) -> int:
    mapping = {
        "topups": "topups_count",
        "deductions": "deductions_count",
        "referrals_l1": "referrals_l1_count",
        "referrals_l2": "referrals_l2_count",
        "partner_commissions": "commission_rows_count",
        "withdrawals": "withdrawals_count",
    }
    return int(summary.get(mapping.get(section, ""), 0) or 0)


def _format_admin_finance_overview(report: dict) -> str:
    summary = report.get("summary") or {}
    lines = [
        "📒 <b>Финансы и рефералы</b>",
        "",
        "<b>Пополнения:</b>",
        f"• Всего: {_code(summary.get('topups_count', 0))}",
        f"• Завершено: {_code(summary.get('completed_topups_count', 0))} "
        f"на {_code(_money(summary.get('completed_revenue_rub')))} ₽",
        f"• Ожидают: {_code(summary.get('pending_topups_count', 0))} "
        f"• ошибок/отмен: {_code(summary.get('failed_topups_count', 0))}",
        f"• Куплено бананов: {_code(summary.get('completed_credits', 0))}",
        "",
        "<b>Списания:</b>",
        f"• Операций: {_code(summary.get('deductions_count', 0))}",
        f"• Списано: {_code(_money(summary.get('deductions_cost')))} 🍌",
        "",
        "<b>Реферальные линии:</b>",
        f"• 1 линия: {_code(summary.get('referrals_l1_count', 0))} "
        f"(платящих: {_code(summary.get('paid_referrals_l1_count', 0))})",
        f"• 2 линия: {_code(summary.get('referrals_l2_count', 0))}",
        "",
        "<b>Партнёрские выводы:</b>",
        f"• Заявок всего: {_code(summary.get('withdrawals_count', 0))}",
        f"• В ожидании: {_code(_money(summary.get('withdrawals_requested_rub')))} ₽",
        f"• Выплачено: {_code(_money(summary.get('withdrawals_completed_rub')))} ₽",
        "",
        "Откройте нужный раздел для последних строк или скачайте XLS целиком.",
    ]
    return "\n".join(lines)


def _format_admin_finance_preview_row(section: str, row: dict) -> str:
    if section == "topups":
        return (
            f"• #{_html(row.get('id'))} "
            f"ID {_code(row.get('telegram_id'))} "
            f"• {_code(_money(row.get('amount_rub')))} ₽ "
            f"• {_code(row.get('credits'))}🍌 "
            f"• {_code(row.get('status'))} "
            f"• {_code(_short(row.get('created_at'), 19))}"
        )
    if section == "deductions":
        model = row.get("model") or row.get("preset_id") or row.get("type") or row.get("source")
        return (
            f"• {_html(row.get('source'))} #{_html(row.get('id'))} "
            f"ID {_code(row.get('telegram_id'))} "
            f"• {_code(_money(row.get('cost')))}🍌 "
            f"• {_code(row.get('status'))} "
            f"• {_code(_short(model, 28))} "
            f"• {_code(_short(row.get('created_at'), 19))}"
        )
    if section == "referrals_l1":
        return (
            f"• {_code(row.get('referrer_telegram_id'))} → "
            f"{_code(row.get('referred_telegram_id'))} "
            f"• оплат {_code(row.get('payments_count'))} "
            f"• {_code(_money(row.get('paid_rub')))} ₽ "
            f"• 2 линия {_code(row.get('subrefs_count'))}"
        )
    if section == "referrals_l2":
        return (
            f"• {_code(row.get('root_partner_telegram_id'))} → "
            f"{_code(row.get('line1_telegram_id'))} → "
            f"{_code(row.get('line2_telegram_id'))} "
            f"• оплат {_code(row.get('payments_count'))} "
            f"• {_code(_money(row.get('paid_rub')))} ₽"
        )
    if section == "partner_commissions":
        return (
            f"• tx#{_html(row.get('transaction_id'))} "
            f"payer {_code(row.get('payer_telegram_id'))} "
            f"• {_code(_money(row.get('amount_rub')))} ₽ "
            f"• L1 {_code(row.get('level1_partner_telegram_id'))}: "
            f"{_code(_money(row.get('level1_commission_rub')))} ₽ "
            f"• L2 {_code(row.get('level2_partner_telegram_id') or '—')}: "
            f"{_code(_money(row.get('level2_commission_rub')))} ₽"
        )
    if section == "withdrawals":
        return (
            f"• #{_html(row.get('id'))} "
            f"ID {_code(row.get('telegram_id'))} "
            f"• {_code(_money(row.get('amount_rub')))} ₽ "
            f"• {_code(row.get('status'))} "
            f"• {_code(_short(row.get('method'), 24))} "
            f"• {_code(_short(row.get('created_at'), 19))}"
        )
    return f"• {_code(row)}"


def _format_admin_finance_section_text(section: str, report: dict) -> str:
    title = ADMIN_FINANCE_SECTION_TITLES.get(section, section)
    rows = report.get(section) or []
    summary = report.get("summary") or {}
    total = _admin_finance_total_for_section(section, summary)
    lines = [
        f"📒 <b>{_html(title)}</b>",
        "",
        f"• Всего строк: {_code(total)}",
        f"• Показано: {_code(min(len(rows), 10))} из {_code(len(rows))}",
        "",
    ]
    if section == "partner_commissions":
        lines.extend(
            [
                "Начисления восстановлены расчётно по завершённым платежам "
                "и текущим процентам программы.",
                "",
            ]
        )

    if not rows:
        lines.append("Нет данных в этом разделе.")
    else:
        for row in rows[:10]:
            lines.append(_format_admin_finance_preview_row(section, row))

    lines.extend(["", "Для полной детализации скачайте XLS раздела."])
    return "\n".join(lines)


def _xls_cell_limit(key: str) -> int:
    return ADMIN_FINANCE_LONG_CELL_LIMITS.get(key, 8000)


def _xls_safe(value, max_chars: int = 8000) -> str:
    if value is None:
        text = ""
    elif isinstance(value, float):
        text = f"{value:.2f}"
    else:
        text = str(value)
    text = text.replace("\x00", "")
    if len(text) > max_chars:
        text = f"{text[: max_chars - 3]}..."
    if text[:1] in {"=", "+", "-", "@"}:
        text = f"'{text}"
    return html_utils.escape(text)


def _build_admin_finance_xls(report: dict, section: str) -> tuple[bytes, str]:
    if section == "all":
        section_keys = ADMIN_FINANCE_SECTION_ORDER
        title = "Финансово-реферальный отчёт"
        file_suffix = "all"
    else:
        section_keys = [section]
        title = ADMIN_FINANCE_SECTION_TITLES.get(section, section)
        file_suffix = section

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts = [
        "\ufeff<html><head><meta charset=\"utf-8\">",
        "<style>",
        "body{font-family:Arial,sans-serif;font-size:12px}",
        "table{border-collapse:collapse;margin-bottom:24px}",
        "th,td{border:1px solid #999;padding:4px;vertical-align:top}",
        "th{background:#e8eef7;font-weight:bold}",
        "td{mso-number-format:'\\@'}",
        "</style></head><body>",
        f"<h1>{_xls_safe(title)}</h1>",
        f"<p>Сформировано: {_xls_safe(generated_at)}. "
        f"Лимит строк на раздел: {_xls_safe(report.get('limit'))}.</p>",
    ]

    for section_key in section_keys:
        rows = report.get(section_key) or []
        columns = ADMIN_FINANCE_COLUMNS[section_key]
        parts.append(
            f"<h2>{_xls_safe(ADMIN_FINANCE_SECTION_TITLES[section_key])}</h2>"
        )
        parts.append("<table><thead><tr>")
        for _, label in columns:
            parts.append(f"<th>{_xls_safe(label)}</th>")
        parts.append("</tr></thead><tbody>")
        if not rows:
            parts.append(
                f"<tr><td colspan=\"{len(columns)}\">Нет данных</td></tr>"
            )
        else:
            for row in rows:
                parts.append("<tr>")
                for key, _ in columns:
                    parts.append(
                        f"<td>{_xls_safe(row.get(key), _xls_cell_limit(key))}</td>"
                    )
                parts.append("</tr>")
        parts.append("</tbody></table>")

    notes = report.get("notes") or []
    if notes:
        parts.append("<h2>Примечания</h2><ul>")
        for note in notes:
            parts.append(f"<li>{_xls_safe(note)}</li>")
        parts.append("</ul>")

    parts.append("</body></html>")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"admin_finance_{file_suffix}_{stamp}.xls"
    return "".join(parts).encode("utf-8"), filename


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
    """Список видео-моделей с ценой за секунду."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await callback.message.edit_text(
        "🎬 <b>Цены на видео</b>\n\n"
        "Цена указана за <b>1 секунду</b>. Выберите модель для редактирования.",
        reply_markup=_admin_video_prices_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_video_model_"))
async def admin_video_model(callback: types.CallbackQuery):
    """Детальный экран модели: все длительности + кнопка цены/с."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    model_key = callback.data.replace("admin_video_model_", "", 1)
    video_models = (
        preset_manager.get_price_config()
        .get("costs_reference", {})
        .get("video_models", {})
    )
    model_cfg = video_models.get(model_key)
    if not model_cfg:
        await callback.answer("Модель не найдена", show_alert=True)
        return

    label = VIDEO_MODEL_LABELS.get(model_key, model_key)
    per_sec = _model_per_sec(model_cfg)
    quality_costs = model_cfg.get("quality_costs", {})
    duration_costs = model_cfg.get("duration_costs", {})
    quality_order = {"720p": 0, "1080p": 1, "4k": 2}

    if quality_costs:
        lines = "\n".join(
            f"• {quality} → <code>{cost}</code>🍌/с"
            for quality, cost in sorted(
                quality_costs.items(),
                key=lambda item: (
                    quality_order.get(str(item[0]).lower(), 99),
                    str(item[0]),
                ),
            )
        )
        detail = f"Цены по качеству за 1 секунду:\n{lines}"
    elif duration_costs:
        lines = "\n".join(
            f"• {dur}с → <code>{cost}</code>🍌"
            for dur, cost in sorted(duration_costs.items(), key=lambda x: int(x[0]))
        )
        detail = (
            f"Текущие длительности:\n{lines}\n\nЦена за 1с: <code>{per_sec}</code>🍌"
        )
    else:
        base = model_cfg.get("base", model_cfg.get("cost"))
        detail = f"Базовая стоимость: <code>{base}</code>🍌"

    await callback.message.edit_text(
        f"🎬 <b>{label}</b>\n\n{detail}\n\n" "Выберите параметр для изменения:",
        reply_markup=_admin_video_model_keyboard(model_key),
        parse_mode="HTML",
    )
    await callback.answer()


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
    """Запрашивает новую цену для видео-модели (конкретная длительность, base или persec)."""
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

    model_label = VIDEO_MODEL_LABELS.get(model_key, model_key)
    return_to = f"admin_video_model_{model_key}"

    if field == "persec":
        current_value = float(_model_per_sec(model))
        hint_text = (
            "Введите новую цену за <b>1 секунду</b>.\n"
            "Все длительности будут пересчитаны автоматически."
        )
        param_label = "цена/с"
    elif field == "base":
        current_value = model.get("base", model.get("cost"))
        hint_text = "Введите новую базовую стоимость."
        param_label = "базовая цена"
    elif field.startswith("q"):
        quality = field[1:]
        quality_costs = model.get("quality_costs") or {}
        current_value = quality_costs.get(quality)
        hint_text = f"Введите стоимость качества <b>{quality}</b> за <b>1 секунду</b>."
        param_label = f"качество {quality}"
    else:
        current_value = (model.get("duration_costs") or {}).get(field)
        hint_text = f"Введите новую стоимость для длительности <b>{field} сек</b>."
        param_label = f"{field} сек"

    if current_value is None:
        await callback.answer("Цена не найдена", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_price_value)
    await state.update_data(
        price_target="video",
        price_key=model_key,
        price_field=field,
        current_price_value=current_value,
        return_to=return_to,
    )

    await callback.message.edit_text(
        f"🎬 <b>{model_label}</b> — {param_label}\n\n"
        f"Текущее значение: <code>{current_value}</code>🍌\n\n"
        f"{hint_text}",
        reply_markup=get_back_keyboard(return_to),
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

    field = data.get("price_field", "")
    if field == "persec":
        success_text = (
            "✅ <b>Цена за секунду обновлена</b>\n\n"
            f"Было: <code>{old_value}</code>🍌/с\n"
            f"Стало: <code>{new_value}</code>🍌/с\n\n"
            "Все длительности пересчитаны автоматически."
        )
    else:
        success_text = (
            "✅ <b>Цена обновлена</b>\n\n"
            f"Было: <code>{old_value}</code>\n"
            f"Стало: <code>{new_value}</code>"
        )

    await message.answer(
        success_text,
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


@router.callback_query(F.data == "admin_finance")
async def admin_finance_menu(callback: types.CallbackQuery, state: FSMContext):
    """Сводка по пополнениям, списаниям и реферальным линиям."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await state.clear()
    report = await get_admin_finance_report(ADMIN_FINANCE_PREVIEW_LIMIT)
    await callback.message.edit_text(
        _format_admin_finance_overview(report),
        reply_markup=_admin_finance_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_finance_xls_"))
async def admin_finance_xls(callback: types.CallbackQuery):
    """Отправляет Excel-совместимый XLS по финансовому разделу."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    section = callback.data.replace("admin_finance_xls_", "", 1)
    if section != "all" and section not in ADMIN_FINANCE_SECTION_TITLES:
        await callback.answer("Раздел не найден", show_alert=True)
        return

    await callback.answer("Готовлю XLS...")
    report = await get_admin_finance_report(ADMIN_FINANCE_XLS_LIMIT)
    file_bytes, filename = _build_admin_finance_xls(report, section)
    limited_by_size = False
    if len(file_bytes) > ADMIN_FINANCE_TELEGRAM_MAX_BYTES:
        logger.warning(
            "Admin finance XLS too large before send: section=%s size=%s, retrying with limit=%s",
            section,
            len(file_bytes),
            ADMIN_FINANCE_XLS_FALLBACK_LIMIT,
        )
        report = await get_admin_finance_report(ADMIN_FINANCE_XLS_FALLBACK_LIMIT)
        file_bytes, filename = _build_admin_finance_xls(report, section)
        limited_by_size = True

    title = (
        "весь финансово-реферальный отчёт"
        if section == "all"
        else ADMIN_FINANCE_SECTION_TITLES[section]
    )
    caption = f"📤 XLS: {title}"
    if limited_by_size:
        caption += "\nФайл был уменьшен до 1000 строк на раздел, чтобы пройти лимит Telegram."

    try:
        await callback.message.answer_document(
            BufferedInputFile(file_bytes, filename=filename),
            caption=caption,
        )
    except TelegramEntityTooLarge:
        logger.exception(
            "Admin finance XLS is still too large: section=%s size=%s",
            section,
            len(file_bytes),
        )
        await callback.message.answer(
            "❌ XLS всё ещё слишком большой для Telegram. "
            "Скачайте отдельные разделы или напишите мне — уменьшу выгрузку ещё сильнее.",
            reply_markup=_admin_finance_keyboard(),
        )
    except TelegramAPIError:
        logger.exception("Failed to send admin finance XLS: section=%s", section)
        await callback.message.answer(
            "❌ Не удалось отправить XLS. Ошибка Telegram уже записана в лог.",
            reply_markup=_admin_finance_keyboard(),
        )


@router.callback_query(F.data.startswith("admin_finance_"))
async def admin_finance_section(callback: types.CallbackQuery, state: FSMContext):
    """Показывает предпросмотр выбранного финансового раздела."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    section = callback.data.replace("admin_finance_", "", 1)
    if section not in ADMIN_FINANCE_SECTION_TITLES:
        await callback.answer("Раздел не найден", show_alert=True)
        return

    await state.clear()
    report = await get_admin_finance_report(ADMIN_FINANCE_PREVIEW_LIMIT)
    await callback.message.edit_text(
        _format_admin_finance_section_text(section, report),
        reply_markup=_admin_finance_section_keyboard(section),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_partners")
async def admin_partners_menu(callback: types.CallbackQuery, state: FSMContext):
    """Сводка по партнёрам и реферальной статистике."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await state.clear()
    stats = await get_admin_partner_stats()
    await callback.message.edit_text(
        _format_admin_partners_text(stats),
        reply_markup=_admin_partners_keyboard(stats.get("top_partners", [])),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_partner_withdrawals")
async def admin_partner_withdrawals(callback: types.CallbackQuery, state: FSMContext):
    """Показывает очередь заявок на вывод партнёров."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await state.clear()
    withdrawals = await get_pending_partner_withdrawals()
    await callback.message.edit_text(
        _format_admin_withdrawals_text(withdrawals),
        reply_markup=_admin_withdrawals_keyboard(withdrawals),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_partner_withdrawal_"))
async def admin_partner_withdrawal_detail(
    callback: types.CallbackQuery, state: FSMContext
):
    """Показывает детальную карточку заявки на вывод."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    withdrawal_id = int(callback.data.replace("admin_partner_withdrawal_", ""))
    withdrawal = await get_partner_withdrawal_request(withdrawal_id)
    if not withdrawal:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_text(
        _format_admin_withdrawal_detail_text(withdrawal),
        reply_markup=_admin_withdrawal_detail_keyboard(withdrawal_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_partner_lookup")
async def admin_partner_lookup(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает Telegram ID партнёра для просмотра статистики."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await state.set_state(AdminStates.waiting_partner_user_id)
    await callback.message.edit_text(
        "🤝 <b>Поиск партнёра</b>\n\n"
        "Введите Telegram ID пользователя, чтобы открыть его реферальную статистику и баланс.",
        reply_markup=get_back_keyboard("admin_partners"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_partner_view_"))
async def admin_partner_view(callback: types.CallbackQuery, state: FSMContext):
    """Показывает детальную партнёрскую карточку."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    telegram_id = int(callback.data.replace("admin_partner_view_", ""))
    details = await get_admin_partner_details(telegram_id)
    if not details:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_text(
        _format_admin_partner_details_text(details),
        reply_markup=_admin_partner_detail_keyboard(telegram_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_partner_user_id)
async def admin_process_partner_user_id(message: types.Message, state: FSMContext):
    """Открывает партнёрскую статистику по введённому Telegram ID."""
    try:
        telegram_id = int((message.text or "").strip())
    except ValueError:
        await message.answer(
            "❌ Неверный формат ID. Введите число.",
            reply_markup=get_back_keyboard("admin_partners"),
        )
        return

    details = await get_admin_partner_details(telegram_id)
    if not details:
        await message.answer(
            f"❌ Пользователь с ID {telegram_id} не найден.",
            reply_markup=get_back_keyboard("admin_partners"),
        )
        return

    await message.answer(
        _format_admin_partner_details_text(details),
        reply_markup=_admin_partner_detail_keyboard(telegram_id),
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data == "admin_users")
async def admin_users_menu(callback: types.CallbackQuery, state: FSMContext):
    """Меню управления пользователями"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await callback.message.edit_text(
        "👥 <b>Управление пользователями</b>\n\nВведите Telegram ID пользователя:",
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
🤝 Рефералов: <code>{stats['referrals_count']}</code>
🎁 Заработано по рефке: <code>{stats['referral_earned']}</code> 🍌
🔗 Рефкод: <code>{stats['referral_code'] or '—'}</code>

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
                        text="🤝 Реферальная статистика",
                        callback_data=f"admin_partner_view_{user_id}",
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
        f"➕ <b>Добавление кредитов</b>\n\n"
        f"Пользователь ID: <code>{user_id}</code>\n"
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
        f"Пользователь ID: <code>{user_id}</code>\n"
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
            f"✅ <b>Успешно!</b>\n\n"
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
    """Запрашивает текст или фото для рассылки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await callback.message.edit_text(
        "📢 <b>Рассылка всем пользователям</b>\n\n"
        "Отправьте текст сообщения или фото с подписью.\n"
        "Можно отправить фото без подписи — пользователи получат только изображение.\n\n"
        "<i>В тексте и подписи поддерживается HTML-форматирование</i>",
        reply_markup=get_back_keyboard("admin_back"),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_broadcast_text)


@router.message(AdminStates.waiting_broadcast_text)
async def admin_process_broadcast_text(message: types.Message, state: FSMContext):
    """Показывает превью рассылки"""
    broadcast_photo_file_id = None

    if message.photo:
        broadcast_photo_file_id = message.photo[-1].file_id
        broadcast_text = (message.caption or "").strip()

        if len(broadcast_text) > BROADCAST_PHOTO_CAPTION_LIMIT:
            await message.answer(
                "❌ Подпись к фото слишком длинная.\n"
                f"Максимум: <code>{BROADCAST_PHOTO_CAPTION_LIMIT}</code> символов.",
                reply_markup=get_back_keyboard("admin_back"),
                parse_mode="HTML",
            )
            return
    elif message.text:
        broadcast_text = message.text.strip()

        if not broadcast_text:
            await message.answer(
                "❌ Текст рассылки пустой. Отправьте текст или фото.",
                reply_markup=get_back_keyboard("admin_back"),
            )
            return

        if len(broadcast_text) > BROADCAST_MESSAGE_LIMIT:
            await message.answer(
                "❌ Текст рассылки слишком длинный.\n"
                f"Максимум: <code>{BROADCAST_MESSAGE_LIMIT}</code> символов.",
                reply_markup=get_back_keyboard("admin_back"),
                parse_mode="HTML",
            )
            return
    else:
        await message.answer(
            "❌ Для рассылки отправьте текст или фото с необязательной подписью.",
            reply_markup=get_back_keyboard("admin_back"),
        )
        return

    await state.update_data(
        broadcast_text=broadcast_text,
        broadcast_photo_file_id=broadcast_photo_file_id,
    )

    if broadcast_photo_file_id:
        await message.answer_photo(
            photo=broadcast_photo_file_id,
            caption=broadcast_text or None,
            parse_mode="HTML" if broadcast_text else None,
        )
        await message.answer(
            "📢 <b>Превью рассылки с фото выше.</b>\n\n"
            "Подтверждаете отправку?",
            reply_markup=_broadcast_confirm_keyboard(),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "📢 <b>Превью рассылки:</b>\n"
            "───────────────\n"
            f"{broadcast_text}\n"
            "───────────────\n"
            "Подтверждаете отправку?",
            reply_markup=_broadcast_confirm_keyboard(),
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
    broadcast_photo_file_id = data.get("broadcast_photo_file_id")

    if not broadcast_text and not broadcast_photo_file_id:
        await callback.message.edit_text(
            "❌ Не найден текст или фото для рассылки.",
            reply_markup=get_admin_keyboard(),
        )
        await state.clear()
        return

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
            if broadcast_photo_file_id:
                await bot.send_photo(
                    user["telegram_id"],
                    photo=broadcast_photo_file_id,
                    caption=broadcast_text or None,
                    parse_mode="HTML" if broadcast_text else None,
                )
            else:
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
