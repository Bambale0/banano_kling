from __future__ import annotations

import asyncio
import html
import logging
from collections.abc import Coroutine
from typing import Any

from aiogram import F, Router, types
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.handlers.generation import _save_reference_image_from_message
from bot.services.gpt_image_25_service import GPTImage25Service, gpt_image_25_service

router = Router(name="admin_test_lab")
logger = logging.getLogger(__name__)

_MAX_REFERENCE_BYTES = 30 * 1024 * 1024
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()
_DELIVERED_TASK_IDS: set[str] = set()

_VARIANT_LABELS = {
    "flare": "⚡ Flare",
    "sunburst": "🎯 Sunburst",
}

class AdminTestLabStates(StatesGroup):
    gpt25_prompt = State()
    gpt25_references = State()


def _is_admin(user_id: int | None) -> bool:
    return bool(user_id is not None and config.is_admin(int(user_id)))


async def _require_admin(callback: types.CallbackQuery) -> bool:
    if _is_admin(callback.from_user.id):
        return True
    await callback.answer("⛔ Нет доступа", show_alert=True)
    return False


def _defaults() -> dict[str, Any]:
    return {
        "gpt25_variant": "flare",
        "gpt25_ratio": "auto",
        "gpt25_resolution": "1K",
        "gpt25_references": [],
        "gpt25_prompt": "",
        "gpt25_last_task_id": "",
        "gpt25_last_model": "",
    }


async def _data(state: FSMContext) -> dict[str, Any]:
    data = await state.get_data()
    missing = {key: value for key, value in _defaults().items() if key not in data}
    if missing:
        await state.update_data(**missing)
        data.update(missing)
    return data


def _short(text: Any, limit: int = 220) -> str:
    value = " ".join(str(text or "").split())
    if not value:
        return "не задан"
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def get_admin_test_lab_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🖼 GPT Image 2.5", callback_data="admin_test_gpt25")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def _test_lab_text() -> str:
    return (
        "🧪 <b>Тест</b>\n\n"
        "Закрытый контур для проверки новых моделей. "
        "Он доступен только Telegram-админам и не списывает бананы.\n\n"
        "Сейчас подключено: <b>GPT Image 2.5</b>."
    )


def _gpt25_dashboard_text(data: dict[str, Any]) -> str:
    refs = list(data.get("gpt25_references") or [])
    variant = str(data.get("gpt25_variant") or "flare")
    mode = "Фото → фото" if refs else "Текст → фото"
    prompt = html.escape(_short(data.get("gpt25_prompt")))
    return (
        "🧪 <b>GPT Image 2.5 · KIE</b>\n\n"
        f"Вариант: <b>{html.escape(_VARIANT_LABELS.get(variant, variant))}</b>\n"
        f"Режим: <b>{mode}</b>\n"
        f"Референсы: <b>{len(refs)}/{GPTImage25Service.MAX_INPUT_IMAGES}</b>\n"
        f"Формат: <b>{html.escape(str(data.get('gpt25_ratio') or 'auto'))}</b>\n"
        f"Разрешение: <b>{html.escape(str(data.get('gpt25_resolution') or '1K'))}</b>\n"
        "\n"
        f"Промпт: <i>{prompt}</i>\n\n"
        "Flare — быстрый основной вариант. Sunburst — более точный вариант "
        "для сложных генераций и правок."
    )


def _gpt25_dashboard_keyboard(data: dict[str, Any]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    variant = str(data.get("gpt25_variant") or "flare")
    for key in ("flare", "sunburst"):
        builder.button(
            text=f"{'✅ ' if variant == key else ''}{_VARIANT_LABELS[key]}",
            callback_data=f"gpt25_variant:{key}",
        )

    refs = list(data.get("gpt25_references") or [])
    builder.button(
        text=f"🖼 Референсы {len(refs)}/{GPTImage25Service.MAX_INPUT_IMAGES}",
        callback_data="gpt25_refs",
    )
    builder.button(text="✍️ Промпт", callback_data="gpt25_prompt")
    builder.button(
        text=f"↔️ {data.get('gpt25_ratio') or 'auto'}",
        callback_data="gpt25_ratio",
    )
    builder.button(
        text=f"✨ {data.get('gpt25_resolution') or '1K'}",
        callback_data="gpt25_resolution",
    )
    builder.button(text="🚀 Запустить", callback_data="gpt25_generate")
    builder.button(text="ℹ️ Возможности", callback_data="gpt25_info")
    if data.get("gpt25_last_task_id"):
        builder.button(text="🔄 Проверить задачу", callback_data="gpt25_check")
    builder.button(text="⬅️ В тесты", callback_data="admin_test_lab")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 2, 2, 1, 1, 1, 1)
    return builder.as_markup()


def _choice_keyboard(
    values: list[str],
    current: str,
    prefix: str,
    *,
    labels: dict[str, str] | None = None,
    width: int = 3,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for value in values:
        label = (labels or {}).get(value, value)
        builder.button(
            text=f"{'✅ ' if value == current else ''}{label}",
            callback_data=f"{prefix}:{value}",
        )
    builder.button(text="⬅️ Назад", callback_data="admin_test_gpt25")
    builder.adjust(width)
    return builder.as_markup()


def _prompt_collection_keyboard(has_prompt: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Готово", callback_data="gpt25_prompt_done")
    if has_prompt:
        builder.button(text="🗑 Очистить", callback_data="gpt25_prompt_clear")
    builder.button(text="⬅️ Настройки", callback_data="admin_test_gpt25")
    builder.adjust(2 if has_prompt else 1, 1)
    return builder.as_markup()


def _reference_collection_keyboard(count: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Готово", callback_data="gpt25_refs_done")
    if count:
        builder.button(text="🗑 Очистить все", callback_data="gpt25_refs_clear")
    builder.button(text="⬅️ Настройки", callback_data="admin_test_gpt25")
    builder.adjust(2 if count else 1, 1)
    return builder.as_markup()


def _task_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Проверить", callback_data="gpt25_check")],
            [InlineKeyboardButton(text="⬅️ GPT Image 2.5", callback_data="admin_test_gpt25")],
        ]
    )


async def _show_gpt25(message: types.Message, state: FSMContext, *, edit: bool) -> None:
    data = await _data(state)
    text = _gpt25_dashboard_text(data)
    markup = _gpt25_dashboard_keyboard(data)
    if edit:
        try:
            await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
            return
        except TelegramAPIError:
            pass
    await message.answer(text, reply_markup=markup, parse_mode="HTML")


def _message_reference_size(message: types.Message) -> int | None:
    if message.photo:
        return message.photo[-1].file_size
    if message.document:
        return message.document.file_size
    return None


def _track_background(coro: Coroutine[Any, Any, Any]) -> None:
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)

    def _done(completed: asyncio.Task[Any]) -> None:
        _BACKGROUND_TASKS.discard(completed)
        try:
            completed.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("GPT Image 2.5 admin test background task failed")

    task.add_done_callback(_done)


async def _send_result_images(
    bot: Any,
    chat_id: int,
    *,
    task_id: str,
    model: str,
    urls: list[str],
) -> None:
    if task_id in _DELIVERED_TASK_IDS:
        return
    _DELIVERED_TASK_IDS.add(task_id)
    for index, url in enumerate(urls[:16]):
        caption = None
        if index == 0:
            caption = (
                "✅ <b>GPT Image 2.5 готово</b>\n"
                f"Модель: <code>{html.escape(model or 'GPT Image 2.5')}</code>\n"
                f"ID задачи: <code>{html.escape(task_id)}</code>"
            )
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=url,
                caption=caption,
                parse_mode="HTML" if caption else None,
            )
        except TelegramAPIError:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"✅ GPT Image 2.5 · ID задачи: <code>{html.escape(task_id)}</code>\n"
                    f"Результат: {html.escape(url)}"
                ),
                parse_mode="HTML",
            )


async def _poll_and_deliver(
    bot: Any,
    chat_id: int,
    task_id: str,
    model: str,
) -> None:
    record = await gpt_image_25_service.wait_for_result(task_id)
    state = str(record.get("state") or "unknown").lower()
    if state in GPTImage25Service.TERMINAL_SUCCESS:
        urls = list(record.get("result_urls") or [])
        if urls:
            await _send_result_images(
                bot,
                chat_id,
                task_id=task_id,
                model=str(record.get("model") or model),
                urls=urls,
            )
            return
        await bot.send_message(
            chat_id,
            "⚠️ GPT Image 2.5 завершил задачу без URL результата.\n"
            f"ID задачи: <code>{html.escape(task_id)}</code>",
            parse_mode="HTML",
        )
        return

    error = str(record.get("error") or "").strip()
    code = str(record.get("error_code") or "").strip()
    suffix = f"\nКод: <code>{html.escape(code)}</code>" if code else ""
    await bot.send_message(
        chat_id,
        "❌ <b>GPT Image 2.5: задача не завершилась успешно.</b>\n"
        f"Статус: <code>{html.escape(state)}</code>\n"
        f"ID задачи: <code>{html.escape(task_id)}</code>"
        f"{suffix}"
        + (f"\n{html.escape(error)}" if error else ""),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_test_lab")
async def open_admin_test_lab(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.set_state(None)
    if callback.message is not None:
        try:
            await callback.message.edit_text(
                _test_lab_text(),
                reply_markup=get_admin_test_lab_keyboard(),
                parse_mode="HTML",
            )
        except TelegramAPIError:
            await callback.message.answer(
                _test_lab_text(),
                reply_markup=get_admin_test_lab_keyboard(),
                parse_mode="HTML",
            )
    await callback.answer()


@router.callback_query(F.data == "admin_test_gpt25")
async def open_gpt25(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.set_state(None)
    if callback.message is not None:
        await _show_gpt25(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("gpt25_variant:"))
async def set_variant(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    variant = (callback.data or "").split(":", 1)[1]
    if variant not in GPTImage25Service.VARIANTS:
        await callback.answer("Неизвестный вариант", show_alert=True)
        return
    await state.update_data(gpt25_variant=variant)
    if callback.message is not None:
        await _show_gpt25(callback.message, state, edit=True)
    await callback.answer("Вариант выбран")


@router.callback_query(F.data == "gpt25_ratio")
async def choose_ratio(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    current = str((await _data(state)).get("gpt25_ratio") or "auto")
    data = await _data(state)
    has_references = bool(data.get("gpt25_references"))
    values = list(
        GPTImage25Service.IMAGE_ASPECT_RATIOS
        if has_references
        else GPTImage25Service.TEXT_ASPECT_RATIOS
    )
    if callback.message is not None:
        await callback.message.edit_text(
            "↔️ <b>GPT Image 2.5 · формат</b>\n\n"
            "Все значения из текущей KIE-спеки модели.",
            reply_markup=_choice_keyboard(values, current, "gpt25_ratio_set", width=3),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("gpt25_ratio_set:"))
async def set_ratio(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    value = (callback.data or "").split(":", 1)[1]
    data = await _data(state)
    allowed = (
        GPTImage25Service.IMAGE_ASPECT_RATIOS
        if data.get("gpt25_references")
        else GPTImage25Service.TEXT_ASPECT_RATIOS
    )
    if value not in allowed:
        await callback.answer("Формат не поддерживается для этого режима", show_alert=True)
        return
    await state.update_data(gpt25_ratio=value)
    if callback.message is not None:
        await _show_gpt25(callback.message, state, edit=True)
    await callback.answer("Формат выбран")


@router.callback_query(F.data == "gpt25_resolution")
async def choose_resolution(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    current = str((await _data(state)).get("gpt25_resolution") or "1K")
    if callback.message is not None:
        await callback.message.edit_text(
            "✨ <b>GPT Image 2.5 · разрешение</b>",
            reply_markup=_choice_keyboard(
                ["1K", "2K", "4K"], current, "gpt25_resolution_set", width=3
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("gpt25_resolution_set:"))
async def set_resolution(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    value = (callback.data or "").split(":", 1)[1].upper()
    if value not in GPTImage25Service.RESOLUTIONS:
        await callback.answer("Разрешение не поддерживается", show_alert=True)
        return
    await state.update_data(gpt25_resolution=value)
    if callback.message is not None:
        await _show_gpt25(callback.message, state, edit=True)
    await callback.answer("Разрешение выбрано")


@router.callback_query(F.data == "gpt25_prompt")
async def start_prompt(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    data = await _data(state)
    prompt = str(data.get("gpt25_prompt") or "")
    await state.set_state(AdminTestLabStates.gpt25_prompt)
    if callback.message is not None:
        await callback.message.edit_text(
            "✍️ <b>Промпт GPT Image 2.5</b>\n\n"
            "Отправляйте текст частями. Я соберу их в один промпт до 20 000 символов.\n"
            f"Сейчас: <b>{len(prompt)}/{GPTImage25Service.MAX_PROMPT_CHARS}</b>",
            reply_markup=_prompt_collection_keyboard(bool(prompt)),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(AdminTestLabStates.gpt25_prompt)
async def receive_prompt_part(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        await state.clear()
        return
    part = str(message.text or message.caption or "").strip()
    if not part:
        await message.answer("Нужен текстовый фрагмент промпта.")
        return
    data = await _data(state)
    current = str(data.get("gpt25_prompt") or "")
    combined = f"{current}\n{part}".strip() if current else part
    if len(combined) > GPTImage25Service.MAX_PROMPT_CHARS:
        await message.answer(
            f"Лимит KIE для этой модели — {GPTImage25Service.MAX_PROMPT_CHARS} символов. "
            f"Сейчас уже {len(current)}."
        )
        return
    await state.update_data(gpt25_prompt=combined)
    await message.answer(
        f"✅ Добавлено. Промпт: <b>{len(combined)}/{GPTImage25Service.MAX_PROMPT_CHARS}</b>",
        reply_markup=_prompt_collection_keyboard(True),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "gpt25_prompt_done")
async def finish_prompt(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.set_state(None)
    if callback.message is not None:
        await _show_gpt25(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(F.data == "gpt25_prompt_clear")
async def clear_prompt(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.update_data(gpt25_prompt="")
    await state.set_state(AdminTestLabStates.gpt25_prompt)
    if callback.message is not None:
        await callback.message.edit_text(
            "✍️ <b>Промпт GPT Image 2.5</b>\n\n"
            "Промпт очищен. Отправьте новый текст.",
            reply_markup=_prompt_collection_keyboard(False),
            parse_mode="HTML",
        )
    await callback.answer("Очищено")


@router.callback_query(F.data == "gpt25_refs")
async def start_references(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    data = await _data(state)
    refs = list(data.get("gpt25_references") or [])
    await state.set_state(AdminTestLabStates.gpt25_references)
    if callback.message is not None:
        await callback.message.edit_text(
            "🖼 <b>Референсы GPT Image 2.5</b>\n\n"
            "Отправляйте JPEG, PNG или WEBP по одному или альбомом. "
            "KIE допускает до 16 файлов, каждый до 30 МБ.\n"
            f"Сейчас: <b>{len(refs)}/{GPTImage25Service.MAX_INPUT_IMAGES}</b>",
            reply_markup=_reference_collection_keyboard(len(refs)),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(AdminTestLabStates.gpt25_references)
async def receive_reference(message: types.Message, state: FSMContext) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        await state.clear()
        return
    data = await _data(state)
    refs = list(data.get("gpt25_references") or [])
    if len(refs) >= GPTImage25Service.MAX_INPUT_IMAGES:
        await message.answer(
            "Достигнут лимит 16 референсов.",
            reply_markup=_reference_collection_keyboard(len(refs)),
        )
        return

    file_size = _message_reference_size(message)
    if file_size is not None and file_size > _MAX_REFERENCE_BYTES:
        await message.answer("❌ Файл больше 30 МБ — KIE его не принимает.")
        return

    url, error = await _save_reference_image_from_message(
        message,
        original_filename_prefix="gpt25-test",
    )
    if error or not url:
        await message.answer(error or "❌ Не удалось сохранить изображение.")
        return
    if url not in refs:
        refs.append(url)
    await state.update_data(gpt25_references=refs)

    if len(refs) >= GPTImage25Service.MAX_INPUT_IMAGES:
        await message.answer(
            "✅ Загружено 16/16 референсов — максимум по KIE. Нажмите «Готово».",
            reply_markup=_reference_collection_keyboard(len(refs)),
        )
        return

    await message.answer(
        f"✅ Референс добавлен: <b>{len(refs)}/{GPTImage25Service.MAX_INPUT_IMAGES}</b>",
        reply_markup=_reference_collection_keyboard(len(refs)),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "gpt25_refs_done")
async def finish_references(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    await state.set_state(None)
    if callback.message is not None:
        await _show_gpt25(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(F.data == "gpt25_refs_clear")
async def clear_references(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    data = await _data(state)
    updates: dict[str, Any] = {"gpt25_references": []}
    if str(data.get("gpt25_ratio") or "auto") not in GPTImage25Service.TEXT_ASPECT_RATIOS:
        updates["gpt25_ratio"] = "auto"
    await state.update_data(**updates)
    await state.set_state(AdminTestLabStates.gpt25_references)
    if callback.message is not None:
        await callback.message.edit_text(
            "🖼 <b>Референсы GPT Image 2.5</b>\n\n"
            "Референсы очищены. Отправьте новые или нажмите «Готово».",
            reply_markup=_reference_collection_keyboard(0),
            parse_mode="HTML",
        )
    await callback.answer("Очищено")


@router.callback_query(F.data == "gpt25_info")
async def gpt25_info(callback: types.CallbackQuery) -> None:
    if not await _require_admin(callback):
        return
    if callback.message is not None:
        await callback.message.edit_text(
            "ℹ️ <b>GPT Image 2.5 · KIE API</b>\n\n"
            "• <b>Flare</b>: основной быстрый вариант.\n"
            "• <b>Sunburst</b>: точнее и медленнее, для сложных правок.\n"
            "• Text-to-Image и Image-to-Image выбираются автоматически.\n"
            "• До <b>16</b> JPEG/PNG/WEBP референсов, до <b>30 МБ</b> каждый.\n"
            "• Промпт: до <b>20 000</b> символов.\n"
            "• Разрешение: <b>1K / 2K / 4K</b>.\n"
            "• Text-to-Image форматы: auto, 1:1, 3:2, 2:3, 4:3, 3:4, 16:9, "
            "9:16, 21:9, 27:16, 16:27, 9:8, 8:9.\n"
            "• Image-to-Image дополнительно: 5:4, 4:5, 2:1, 1:2, 3:1, 1:3, 9:21.\n"
            "• В текущей KIE API-форме нет отдельного параметра background: "
            "прозрачный фон при необходимости задаётся текстом промпта.\n\n"
            "Sketch, templates и комментарии относятся к интерфейсу ChatGPT; "
            "в KIE Market для GPT Image 2.5 не добавляю полей, которых нет в текущей API-спеке.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_test_gpt25")]
                ]
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "gpt25_generate")
async def generate_gpt25(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    if callback.message is None:
        return
    data = await _data(state)
    prompt = str(data.get("gpt25_prompt") or "").strip()
    if not prompt:
        await callback.answer("Сначала задайте промпт", show_alert=True)
        return
    if not config.KIE_AI_API_KEY:
        await callback.answer("KIE_AI_API_KEY не настроен", show_alert=True)
        return

    refs = list(data.get("gpt25_references") or [])
    variant = str(data.get("gpt25_variant") or "flare")
    try:
        await callback.answer("Отправляю в KIE…")
        result = await gpt_image_25_service.generate(
            prompt=prompt,
            variant=variant,
            input_urls=refs,
            aspect_ratio=str(data.get("gpt25_ratio") or "auto"),
            resolution=str(data.get("gpt25_resolution") or "1K"),
        )
    except (ValueError, TypeError) as exc:
        await callback.message.edit_text(
            f"❌ <b>Некорректные параметры:</b> {html.escape(str(exc))}",
            reply_markup=_gpt25_dashboard_keyboard(data),
            parse_mode="HTML",
        )
        return
    except Exception:
        logger.exception("GPT Image 2.5 admin test submit failed")
        await callback.message.edit_text(
            "❌ KIE недоступен или запрос не удалось отправить.",
            reply_markup=_gpt25_dashboard_keyboard(data),
        )
        return

    if not isinstance(result, dict) or not result.get("task_id"):
        provider_message = ""
        if isinstance(result, dict):
            provider_message = str(result.get("message") or result.get("error") or "")
        await callback.message.edit_text(
            "❌ <b>KIE не создал задачу.</b>"
            + (f"\n\n{html.escape(provider_message)}" if provider_message else ""),
            reply_markup=_gpt25_dashboard_keyboard(data),
            parse_mode="HTML",
        )
        return

    task_id = str(result["task_id"])
    provider_model = str(result.get("provider_model") or "")
    await state.update_data(
        gpt25_last_task_id=task_id,
        gpt25_last_model=provider_model,
    )
    await callback.message.edit_text(
        "⏳ <b>GPT Image 2.5 запущен</b>\n\n"
        f"Модель: <code>{html.escape(provider_model)}</code>\n"
        f"ID задачи: <code>{html.escape(task_id)}</code>\n\n"
        "Результат придёт сюда автоматически. Можно проверить статус вручную.",
        reply_markup=_task_keyboard(),
        parse_mode="HTML",
    )
    _track_background(
        _poll_and_deliver(
            callback.bot,
            callback.from_user.id,
            task_id,
            provider_model,
        )
    )


@router.callback_query(F.data == "gpt25_check")
async def check_gpt25(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback):
        return
    data = await _data(state)
    task_id = str(data.get("gpt25_last_task_id") or "").strip()
    if not task_id:
        await callback.answer("Нет последней задачи", show_alert=True)
        return
    await callback.answer("Проверяю…")
    try:
        record = await gpt_image_25_service.get_task_record(task_id)
    except Exception:
        logger.exception("GPT Image 2.5 admin test status lookup failed")
        await callback.answer("Не удалось получить статус KIE", show_alert=True)
        return

    status = str(record.get("state") or "unknown").lower()
    if status in GPTImage25Service.TERMINAL_SUCCESS and record.get("result_urls"):
        if callback.message is not None:
            await callback.message.edit_text(
                "✅ <b>Задача готова</b>\n"
                f"ID задачи: <code>{html.escape(task_id)}</code>",
                reply_markup=_task_keyboard(),
                parse_mode="HTML",
            )
        await _send_result_images(
            callback.bot,
            callback.from_user.id,
            task_id=task_id,
            model=str(record.get("model") or data.get("gpt25_last_model") or ""),
            urls=list(record.get("result_urls") or []),
        )
        return

    if status in GPTImage25Service.TERMINAL_FAILURE:
        error = html.escape(str(record.get("error") or "Ошибка провайдера"))
        if callback.message is not None:
            await callback.message.edit_text(
                "❌ <b>Задача завершилась ошибкой</b>\n"
                f"Статус: <code>{html.escape(status)}</code>\n"
                f"ID задачи: <code>{html.escape(task_id)}</code>\n"
                f"{error}",
                reply_markup=_task_keyboard(),
                parse_mode="HTML",
            )
        return

    progress = record.get("progress")
    progress_text = f"\nПрогресс: <code>{html.escape(str(progress))}</code>" if progress is not None else ""
    if callback.message is not None:
        await callback.message.edit_text(
            "⏳ <b>Задача ещё выполняется</b>\n"
            f"Статус: <code>{html.escape(status)}</code>{progress_text}\n"
            f"ID задачи: <code>{html.escape(task_id)}</code>",
            reply_markup=_task_keyboard(),
            parse_mode="HTML",
        )
