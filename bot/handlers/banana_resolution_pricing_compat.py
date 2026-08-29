from __future__ import annotations

import sys
from types import ModuleType

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from bot.quality_pricing import QUALITY_COSTS, refresh_quality_pricing
from bot.services.preset_manager import preset_manager
from bot.states import AdminStates


router = Router()
_BANANA_MODEL_KEYS = ("nano-banana-pro", "banana_2")
_BANANA_LEGACY_KEYS = ("banana_pro", "nanobanana", "banana_2")
_QUALITY_CALLBACKS = {
    "admin_banana_quality_1K": "1K",
    "admin_banana_quality_2K": "2K",
    "admin_banana_quality_4K": "4K",
}
_admin_module: ModuleType | None = None
_original_image_prices_keyboard = None
_original_update_price_value = None


def _quality_costs() -> dict[str, float]:
    config = preset_manager.get_price_config()
    raw = config.get("costs_reference", {}).get("image_quality_costs", {})
    return {
        quality: float(raw.get(quality, QUALITY_COSTS[quality]))
        for quality in ("1K", "2K", "4K")
    }


def _format_cost(value: float) -> str:
    return f"{float(value):g}"


def _refresh_loaded_miniapp_catalog() -> None:
    """Keep already-imported Mini App model metadata in sync with live tariffs."""
    miniapp = sys.modules.get("bot.miniapp")
    if miniapp is None:
        return
    models = getattr(miniapp, "IMAGE_MODELS", ())
    quality_costs = {quality: QUALITY_COSTS[quality] for quality in ("1K", "2K", "4K")}
    for model in models:
        if not isinstance(model, dict) or model.get("id") not in {"banana_pro", "banana_2"}:
            continue
        model["cost"] = QUALITY_COSTS["2K"]
        model["quality_costs"] = dict(quality_costs)


def _banana_quality_keyboard() -> types.InlineKeyboardMarkup:
    costs = _quality_costs()
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text=f"1K → {_format_cost(costs['1K'])}🍌",
                    callback_data="admin_banana_quality_1K",
                ),
                types.InlineKeyboardButton(
                    text=f"2K → {_format_cost(costs['2K'])}🍌",
                    callback_data="admin_banana_quality_2K",
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text=f"4K → {_format_cost(costs['4K'])}🍌",
                    callback_data="admin_banana_quality_4K",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔙 К фото-моделям", callback_data="admin_prices_images"
                )
            ],
        ]
    )


def _patched_image_prices_keyboard() -> types.InlineKeyboardMarkup:
    assert _admin_module is not None
    image_models = (
        preset_manager.get_price_config()
        .get("costs_reference", {})
        .get("image_models", {})
    )
    labels = {
        "seedream_edit": "Seedream 4.5 Edit",
        "flux_pro": "GPT Image 2",
        "grok_imagine_i2i": "Grok Imagine",
        "wan_27": "Wan 2.7 Pro",
    }
    costs = _quality_costs()
    buttons = [
        types.InlineKeyboardButton(
            text=(
                "Nano Banana Pro / 2 • "
                f"1K {_format_cost(costs['1K'])} · "
                f"2K {_format_cost(costs['2K'])} · "
                f"4K {_format_cost(costs['4K'])}🍌"
            ),
            callback_data="admin_banana_quality_prices",
        )
    ]
    for key, value in image_models.items():
        if key in _BANANA_MODEL_KEYS:
            continue
        buttons.append(
            types.InlineKeyboardButton(
                text=f"{labels.get(key, key)} • {value}🍌",
                callback_data=f"admin_price_image_{key}",
            )
        )
    rows = _admin_module._chunk_buttons(buttons) + [
        [types.InlineKeyboardButton(text="🔙 К разделам", callback_data="admin_prices")]
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _patched_update_price_value(target: str, key: str, field: str, value):
    assert _admin_module is not None
    assert _original_update_price_value is not None
    if target != "image_quality":
        return _original_update_price_value(target, key, field, value)

    quality = str(field or "").upper()
    if quality not in {"1K", "2K", "4K"}:
        raise KeyError("image_quality")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError("image quality price must be positive")

    price_config = _admin_module._read_price_config()
    costs_reference = price_config.setdefault("costs_reference", {})
    quality_costs = costs_reference.setdefault("image_quality_costs", {})
    old_value = quality_costs.get(quality, QUALITY_COSTS[quality])
    quality_costs[quality] = value

    # The scalar image-model tariff remains the default 2K price for legacy
    # callers that do not yet pass a resolution. Batch pricing follows it too.
    if quality == "2K":
        image_models = costs_reference.setdefault("image_models", {})
        for model_key in _BANANA_MODEL_KEYS:
            image_models[model_key] = value

        legacy_keys = costs_reference.setdefault("legacy_keys", {})
        for model_key in _BANANA_LEGACY_KEYS:
            if model_key in legacy_keys:
                legacy_keys[model_key] = value

        batch_costs = price_config.setdefault("batch_pricing", {}).setdefault(
            "base_costs", {}
        )
        for model_key in _BANANA_MODEL_KEYS:
            if model_key in batch_costs:
                batch_costs[model_key] = value

    if not preset_manager.update_price_config(price_config):
        raise RuntimeError("price config reload failed")
    refresh_quality_pricing(price_config)
    _refresh_loaded_miniapp_catalog()
    return old_value


@router.callback_query(F.data == "admin_banana_quality_prices")
async def admin_banana_quality_prices(
    callback: types.CallbackQuery, state: FSMContext
) -> None:
    if not preset_manager.is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    await state.clear()
    costs = _quality_costs()
    await callback.message.edit_text(
        "🍌 <b>Nano Banana Pro / Nano Banana 2</b>\n\n"
        "Цены задаются отдельно для каждого разрешения и сразу применяются "
        "к Telegram и Mini App.\n\n"
        f"• 1K → <code>{_format_cost(costs['1K'])}</code> 🍌\n"
        f"• 2K → <code>{_format_cost(costs['2K'])}</code> 🍌\n"
        f"• 4K → <code>{_format_cost(costs['4K'])}</code> 🍌\n\n"
        "Выберите разрешение для изменения:",
        reply_markup=_banana_quality_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.in_(set(_QUALITY_CALLBACKS)))
async def admin_banana_quality_value(
    callback: types.CallbackQuery, state: FSMContext
) -> None:
    if not preset_manager.is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    quality = _QUALITY_CALLBACKS.get(str(callback.data))
    if quality is None:
        await callback.answer("Неизвестное разрешение", show_alert=True)
        return
    current_value = _quality_costs()[quality]
    await state.set_state(AdminStates.waiting_price_value)
    await state.update_data(
        price_target="image_quality",
        price_key="banana_family",
        price_field=quality,
        current_price_value=current_value,
        return_to="admin_banana_quality_prices",
    )
    await callback.message.edit_text(
        f"🍌 <b>Nano Banana — {quality}</b>\n\n"
        f"Текущая стоимость: <code>{_format_cost(current_value)}</code> 🍌\n\n"
        "Отправьте новую стоимость одним сообщением.",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="🔙 К разрешениям",
                        callback_data="admin_banana_quality_prices",
                    )
                ]
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


def install_banana_resolution_pricing(admin_module: ModuleType) -> None:
    """Install config-driven Banana tier pricing without rewriting legacy admin.py."""
    global _admin_module
    global _original_image_prices_keyboard
    global _original_update_price_value

    if getattr(admin_module, "_banana_resolution_pricing_installed", False):
        _admin_module = admin_module
        return

    _admin_module = admin_module
    _original_image_prices_keyboard = admin_module._admin_image_prices_keyboard
    _original_update_price_value = admin_module._update_price_value
    admin_module._admin_image_prices_keyboard = _patched_image_prices_keyboard
    admin_module._update_price_value = _patched_update_price_value
    admin_module._banana_resolution_pricing_installed = True
    refresh_quality_pricing(preset_manager.get_price_config())
    _refresh_loaded_miniapp_catalog()
