from __future__ import annotations

import html
import logging
from types import ModuleType
from typing import Any

from aiogram import F, Router, types
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.handlers.generation import _save_reference_image_from_message
from bot.services.rendergrid_service import RenderGridError, rendergrid_client

router = Router(name="rendergrid_test_compat")
logger = logging.getLogger(__name__)
_admin_module: ModuleType | None = None
_PROVIDER_ERRORS = (RenderGridError, ValueError, TypeError, TimeoutError)

DEFAULT_MODEL = "nano-banana-2"
DEFAULT_RATIO = "1:1"
RATIOS = ("auto", "1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16", "21:9")
RESOLUTIONS = ("auto", "1K", "2K", "4K")


class RenderGridTestStates(StatesGroup):
    waiting_reference_photo = State()
    waiting_prompt = State()


def _is_admin(user_id: int | None) -> bool:
    return bool(user_id and config.is_admin(user_id))


def _defaults() -> dict[str, Any]:
    return {
        "rg_model": DEFAULT_MODEL,
        "rg_model_label": DEFAULT_MODEL,
        "rg_ratio": DEFAULT_RATIO,
        "rg_resolution": "auto",
        "rg_reference_url": None,
        "rg_prompt": "",
        "rg_models": [],
    }


async def _data(state: FSMContext) -> dict[str, Any]:
    data = await state.get_data()
    missing = {k: v for k, v in _defaults().items() if k not in data}
    if missing:
        await state.update_data(**missing)
        data.update(missing)
    return data


def _short(value: Any, limit: int = 80) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return "не задан"
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _dashboard_text(data: dict[str, Any]) -> str:
    model = html.escape(str(data.get("rg_model_label") or data.get("rg_model") or DEFAULT_MODEL))
    ratio = html.escape(str(data.get("rg_ratio") or DEFAULT_RATIO))
    resolution = str(data.get("rg_resolution") or "auto")
    has_photo = bool(data.get("rg_reference_url"))
    prompt = html.escape(_short(data.get("rg_prompt"), 180))
    return (
        "🧪 <b>RenderGrid TEST</b>\n\n"
        f"Режим: <b>{'Фото → фото' if has_photo else 'Текст → фото'}</b>\n"
        f"Модель: <b>{model}</b>\n"
        f"Фото: <b>{'✅ добавлено' if has_photo else 'не добавлено'}</b>\n"
        f"Формат: <b>{ratio}</b>\n"
        f"Качество: <b>{'по модели' if resolution == 'auto' else html.escape(resolution)}</b>\n\n"
        f"Промпт: <i>{prompt}</i>\n\n"
        "Настройте генерацию и нажмите «Создать»."
    )


def _dashboard_keyboard(data: dict[str, Any]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"🤖 {_short(data.get('rg_model_label') or data.get('rg_model'), 34)}",
        callback_data="rg_choose_model",
    )
    if data.get("rg_reference_url"):
        builder.button(text="🖼 Заменить фото", callback_data="rg_add_photo")
        builder.button(text="🗑 Убрать фото", callback_data="rg_remove_photo")
    else:
        builder.button(text="🖼 Добавить фото", callback_data="rg_add_photo")
    builder.button(text="✍️ Промпт", callback_data="rg_set_prompt")
    builder.button(text=f"↔️ {data.get('rg_ratio') or DEFAULT_RATIO}", callback_data="rg_choose_ratio")
    quality = str(data.get("rg_resolution") or "auto")
    builder.button(
        text=f"✨ {'По модели' if quality == 'auto' else quality}",
        callback_data="rg_choose_resolution",
    )
    builder.button(text="🎨 Создать", callback_data="rg_generate")
    builder.button(text="💰 Баланс RenderGrid", callback_data="rg_balance")
    builder.button(text="⬅️ В админку", callback_data="rendergrid_test_back")
    builder.adjust(1, 2, 2, 1, 1, 1)
    return builder.as_markup()


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ К настройкам", callback_data="admin_rendergrid_test")],
            [InlineKeyboardButton(text="🏠 В админку", callback_data="rendergrid_test_back")],
        ]
    )


def _provider_error(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "⌛ <b>RenderGrid:</b> генерация не успела завершиться."
    if isinstance(exc, RenderGridError):
        suffix = f" (HTTP {exc.status})" if exc.status is not None else ""
        return f"❌ <b>RenderGrid:</b> {html.escape(str(exc))}{suffix}"
    return f"❌ <b>Ошибка:</b> {html.escape(str(exc))}"


def _creation_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("id", "creation_id", "task_id"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return _creation_id(payload.get("data"))


def _result_urls(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    for key in ("result_urls", "urls", "images", "outputs"):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        urls: list[str] = []
        for item in value:
            if isinstance(item, str):
                url = item
            elif isinstance(item, dict):
                url = str(item.get("url") or item.get("image_url") or "")
            else:
                continue
            if url.startswith(("http://", "https://")):
                urls.append(url)
        if urls:
            return urls
    return _result_urls(payload.get("data"))


def _model_rows(payload: Any) -> list[dict[str, str]]:
    raw = payload
    if isinstance(raw, dict):
        for key in ("models", "items", "results"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
        else:
            data = raw.get("data")
            if isinstance(data, list):
                raw = data
            elif isinstance(data, dict):
                for key in ("models", "items", "results"):
                    if isinstance(data.get(key), list):
                        raw = data[key]
                        break
                else:
                    raw = data

    if isinstance(raw, dict):
        converted: list[Any] = []
        for key, value in raw.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("id", key)
                converted.append(item)
            elif isinstance(value, str):
                converted.append({"id": key, "name": value})
        raw = converted

    if not isinstance(raw, list):
        return []

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            model_id = item.strip()
            label, price = model_id, ""
        elif isinstance(item, dict):
            model_id = str(
                item.get("id") or item.get("model") or item.get("slug") or item.get("key") or ""
            ).strip()
            label = str(
                item.get("display_name")
                or item.get("label")
                or item.get("name")
                or item.get("title")
                or model_id
            ).strip()
            price_value = item.get("price")
            if price_value is None:
                price_value = item.get("cost")
            if price_value is None:
                price_value = item.get("price_per_image")
            price = str(price_value).strip() if price_value is not None else ""
        else:
            continue
        if model_id and model_id not in seen:
            seen.add(model_id)
            rows.append({"id": model_id, "label": label or model_id, "price": price})
    return rows


def _models_keyboard(models: list[dict[str, str]], current: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index, model in enumerate(models[:40]):
        selected = "✅ " if model["id"] == current else ""
        price = f" • {model['price']}" if model.get("price") else ""
        builder.button(
            text=f"{selected}{_short(model['label'], 42)}{price}",
            callback_data=f"rg_model_select:{index}",
        )
    builder.button(text="⬅️ Назад", callback_data="admin_rendergrid_test")
    builder.adjust(1)
    return builder.as_markup()


def _choice_keyboard(values: tuple[str, ...], current: str, prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for value in values:
        label = "По модели" if value == "auto" else value
        builder.button(
            text=f"{'✅ ' if value == current else ''}{label}",
            callback_data=f"{prefix}:{value}",
        )
    builder.button(text="⬅️ Назад", callback_data="admin_rendergrid_test")
    builder.adjust(3 if prefix == "rg_ratio" else 2)
    return builder.as_markup()


def _patch_admin_keyboard(admin_module: ModuleType) -> None:
    current = admin_module.get_admin_keyboard
    if getattr(current, "__rendergrid_test_patched__", False):
        return

    def patched(*args, **kwargs):
        markup = current(*args, **kwargs)
        rows = [list(row) for row in markup.inline_keyboard]
        if any(
            button.callback_data == "admin_rendergrid_test"
            for row in rows
            for button in row
        ):
            return markup
        row = [InlineKeyboardButton(text="🧪 RenderGrid TEST", callback_data="admin_rendergrid_test")]
        insert_at = len(rows)
        if rows and any(button.callback_data == "back_main" for button in rows[-1]):
            insert_at -= 1
        rows.insert(insert_at, row)
        return InlineKeyboardMarkup(inline_keyboard=rows)

    patched.__rendergrid_test_patched__ = True
    admin_module.get_admin_keyboard = patched


def install_rendergrid_test_compat(admin_module: ModuleType) -> None:
    global _admin_module
    _admin_module = admin_module
    _patch_admin_keyboard(admin_module)


async def _patch_on_startup(**_kwargs: Any) -> None:
    if _admin_module is not None:
        _patch_admin_keyboard(_admin_module)


router.startup.register(_patch_on_startup)


async def _show(message: types.Message, state: FSMContext, *, edit: bool) -> None:
    data = await _data(state)
    if edit:
        try:
            await message.edit_text(
                _dashboard_text(data),
                reply_markup=_dashboard_keyboard(data),
                parse_mode="HTML",
            )
            return
        except TelegramAPIError:
            pass
    await message.answer(
        _dashboard_text(data),
        reply_markup=_dashboard_keyboard(data),
        parse_mode="HTML",
    )


@router.message(Command("rendergrid"))
async def rendergrid_command(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        return
    await state.clear()
    await state.update_data(**_defaults())
    await _show(message, state, edit=False)


@router.callback_query(F.data == "admin_rendergrid_test")
async def rendergrid_open(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    await state.set_state(None)
    await _data(state)
    if callback.message is not None:
        await _show(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(F.data == "rg_choose_model")
async def choose_model(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    if callback.message is None:
        return
    await callback.answer("Загружаю модели…")
    try:
        models = _model_rows(await rendergrid_client.list_models())
    except _PROVIDER_ERRORS as exc:
        await callback.message.edit_text(_provider_error(exc), reply_markup=_back_keyboard(), parse_mode="HTML")
        return
    if not models:
        await callback.message.edit_text("⚠️ RenderGrid не вернул список моделей.", reply_markup=_back_keyboard())
        return
    await state.update_data(rg_models=models)
    current = str((await _data(state)).get("rg_model") or DEFAULT_MODEL)
    await callback.message.edit_text(
        "🤖 <b>Выберите модель</b>\n\nСписок загружен прямо из RenderGrid.",
        reply_markup=_models_keyboard(models, current),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("rg_model_select:"))
async def select_model(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    models = (await _data(state)).get("rg_models") or []
    try:
        model = models[int((callback.data or "").split(":", 1)[1])]
    except (ValueError, IndexError, TypeError):
        await callback.answer("Откройте список моделей ещё раз.", show_alert=True)
        return
    await state.update_data(rg_model=model["id"], rg_model_label=model["label"])
    if callback.message is not None:
        await _show(callback.message, state, edit=True)
    await callback.answer("Модель выбрана")


@router.callback_query(F.data == "rg_add_photo")
async def add_photo(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    await state.set_state(RenderGridTestStates.waiting_reference_photo)
    if callback.message is not None:
        await callback.message.edit_text(
            "🖼 <b>Добавьте фото</b>\n\n"
            "Отправьте одно фото JPEG, PNG или WEBP. Оно станет референсом для генерации.",
            reply_markup=_back_keyboard(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(RenderGridTestStates.waiting_reference_photo)
async def receive_photo(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        await state.clear()
        return
    url, error = await _save_reference_image_from_message(
        message,
        original_filename_prefix="rendergrid",
    )
    if error or not url:
        await message.answer(error or "❌ Не удалось сохранить фото.", reply_markup=_back_keyboard())
        return
    await state.set_state(None)
    await state.update_data(rg_reference_url=url)
    await message.answer("✅ Фото добавлено.")
    await _show(message, state, edit=False)


@router.callback_query(F.data == "rg_remove_photo")
async def remove_photo(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    await state.set_state(None)
    await state.update_data(rg_reference_url=None)
    if callback.message is not None:
        await _show(callback.message, state, edit=True)
    await callback.answer("Фото убрано")


@router.callback_query(F.data == "rg_set_prompt")
async def set_prompt(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    await state.set_state(RenderGridTestStates.waiting_prompt)
    if callback.message is not None:
        await callback.message.edit_text(
            "✍️ <b>Промпт</b>\n\n"
            "Напишите обычным сообщением, что нужно создать или изменить на фото.",
            reply_markup=_back_keyboard(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(RenderGridTestStates.waiting_prompt)
async def receive_prompt(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        await state.clear()
        return
    prompt = (message.text or "").strip()
    if not prompt:
        await message.answer("Нужен текстовый промпт.", reply_markup=_back_keyboard())
        return
    await state.set_state(None)
    await state.update_data(rg_prompt=prompt)
    await _show(message, state, edit=False)


@router.callback_query(F.data == "rg_choose_ratio")
async def choose_ratio(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    current = str((await _data(state)).get("rg_ratio") or DEFAULT_RATIO)
    if callback.message is not None:
        await callback.message.edit_text(
            "↔️ <b>Формат изображения</b>",
            reply_markup=_choice_keyboard(RATIOS, current, "rg_ratio"),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("rg_ratio:"))
async def select_ratio(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    value = (callback.data or "").split(":", 1)[1]
    if value not in RATIOS:
        await callback.answer("Недоступный формат", show_alert=True)
        return
    await state.update_data(rg_ratio=value)
    if callback.message is not None:
        await _show(callback.message, state, edit=True)
    await callback.answer("Формат выбран")


@router.callback_query(F.data == "rg_choose_resolution")
async def choose_resolution(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    current = str((await _data(state)).get("rg_resolution") or "auto")
    if callback.message is not None:
        await callback.message.edit_text(
            "✨ <b>Качество</b>\n\n«По модели» использует значение RenderGrid по умолчанию.",
            reply_markup=_choice_keyboard(RESOLUTIONS, current, "rg_resolution"),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("rg_resolution:"))
async def select_resolution(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    value = (callback.data or "").split(":", 1)[1]
    if value not in RESOLUTIONS:
        await callback.answer("Недоступное качество", show_alert=True)
        return
    await state.update_data(rg_resolution=value)
    if callback.message is not None:
        await _show(callback.message, state, edit=True)
    await callback.answer("Качество выбрано")


def _balance_text(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("balance", "amount", "credits", "wallet_balance", "available"):
            value = payload.get(key)
            if value is not None and not isinstance(value, (dict, list)):
                unit = payload.get("currency") or payload.get("unit") or ""
                return f"{value}{f' {unit}' if unit else ''}"
        return _balance_text(payload.get("data"))
    return str(payload)


@router.callback_query(F.data == "rg_balance")
async def balance(callback: types.CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    if callback.message is None:
        return
    await callback.answer("Проверяю баланс…")
    try:
        text = (
            "💰 <b>Баланс RenderGrid</b>\n\n"
            f"<code>{html.escape(_balance_text(await rendergrid_client.get_balance()))}</code>"
        )
    except _PROVIDER_ERRORS as exc:
        text = _provider_error(exc)
    await callback.message.edit_text(text, reply_markup=_back_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "rg_generate")
async def generate(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    if callback.message is None:
        return

    data = await _data(state)
    model = str(data.get("rg_model") or "").strip()
    prompt = str(data.get("rg_prompt") or "").strip()
    if not model:
        await callback.answer("Сначала выберите модель", show_alert=True)
        return
    if not prompt:
        await callback.answer("Сначала добавьте промпт", show_alert=True)
        return
    if not rendergrid_client.configured:
        await callback.answer("RENDERGRID_API_KEY не задан", show_alert=True)
        return

    payload: dict[str, Any] = {"model": model, "prompt": prompt}
    ratio = str(data.get("rg_ratio") or "")
    if ratio and ratio != "auto":
        payload["aspect_ratio"] = ratio
    resolution = str(data.get("rg_resolution") or "")
    if resolution and resolution != "auto":
        payload["resolution"] = resolution
    reference_url = str(data.get("rg_reference_url") or "").strip()
    if reference_url:
        payload["reference_images"] = [reference_url]

    await callback.answer("Запускаю…")
    await callback.message.edit_text(
        f"⏳ <b>RenderGrid генерирует {'по фото' if reference_url else 'по тексту'}</b>\n\n"
        f"Модель: <b>{html.escape(str(data.get('rg_model_label') or model))}</b>",
        parse_mode="HTML",
    )
    try:
        accepted = await rendergrid_client.generate_image(payload)
        creation_id = _creation_id(accepted)
        final = (
            await rendergrid_client.wait_for_creation(creation_id, timeout_seconds=600)
            if creation_id
            else accepted
        )
    except _PROVIDER_ERRORS as exc:
        await callback.message.edit_text(_provider_error(exc), reply_markup=_back_keyboard(), parse_mode="HTML")
        return

    if isinstance(final, dict) and str(final.get("status") or "").lower() == "failed":
        reason = str(final.get("error") or final.get("message") or "").strip()
        text = "❌ <b>Генерация не удалась.</b>"
        if reason:
            text += f"\n\n{html.escape(reason)}"
        await callback.message.edit_text(text, reply_markup=_back_keyboard(), parse_mode="HTML")
        return

    urls = _result_urls(final)
    if not urls:
        await callback.message.edit_text(
            "⚠️ RenderGrid завершил запрос, но не вернул изображение.",
            reply_markup=_back_keyboard(),
        )
        return

    await callback.message.edit_text(
        f"✅ <b>Готово</b>\n\nИзображений: <b>{len(urls)}</b>",
        reply_markup=_dashboard_keyboard(await _data(state)),
        parse_mode="HTML",
    )
    for index, url in enumerate(urls[:10]):
        try:
            await callback.message.answer_photo(
                url,
                caption=(
                    f"🧪 RenderGrid • {html.escape(str(data.get('rg_model_label') or model))}"
                    if index == 0
                    else None
                ),
                parse_mode="HTML",
            )
        except TelegramAPIError:
            await callback.message.answer(
                f"Готовое изображение: {html.escape(url)}",
                parse_mode="HTML",
            )


@router.callback_query(F.data == "rendergrid_test_back")
async def rendergrid_back(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    await state.clear()
    admin_module = _admin_module
    if admin_module is None or callback.message is None:
        await callback.answer("Админка недоступна", show_alert=True)
        return
    stats = await admin_module.get_admin_stats()
    subscription_required = await admin_module.is_channel_subscription_required()
    await callback.message.edit_text(
        admin_module._format_admin_panel_text(stats, subscription_required),
        reply_markup=admin_module.get_admin_keyboard(subscription_required),
        parse_mode="HTML",
    )
    await callback.answer()
