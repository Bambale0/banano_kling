"""Admin-only NexusAPI Nano Banana sandbox.

Isolated from production billing, history, feed publishing and provider fallback.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from dataclasses import dataclass
from typing import Any

import aiohttp
from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config

logger = logging.getLogger(__name__)
router = Router(name="nexus_admin_test")

_CALLBACK_OPEN = "admin_nexus_test"
_CALLBACK_MODEL_PREFIX = "admin_nexus_model:"
_CALLBACK_SIZE_PREFIX = "admin_nexus_size:"
_CALLBACK_CANCEL = "admin_nexus_cancel"
_TERMINAL_STATUSES = {"completed", "failed"}
_ALLOWED_MODELS = {
    "nano-banana": "Nano Banana",
    "nano-banana-2": "Nano Banana 2",
    "nano-banana-pro": "Nano Banana Pro",
}
_SIZE_MODELS = {"nano-banana-2", "nano-banana-pro"}
_ALLOWED_SIZES = {"2K", "4K"}


class NexusAdminTestState(StatesGroup):
    waiting_for_size = State()
    waiting_for_input = State()


@dataclass(frozen=True)
class NexusSettings:
    api_key: str
    base_url: str
    timeout_seconds: int
    poll_interval_seconds: float

    @classmethod
    def from_env(cls) -> "NexusSettings":
        return cls(
            api_key=os.getenv("NEXUS_API_KEY", "").strip(),
            base_url=os.getenv("NEXUS_API_BASE_URL", "https://nexusapi.dev").strip().rstrip("/"),
            timeout_seconds=max(30, int(os.getenv("NEXUS_API_TIMEOUT_SECONDS", "180"))),
            poll_interval_seconds=max(1.0, float(os.getenv("NEXUS_API_POLL_INTERVAL_SECONDS", "3"))),
        )


def _is_admin(user_id: int | None) -> bool:
    return bool(user_id is not None and config.is_admin(user_id))


def _model_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for model_id, label in _ALLOWED_MODELS.items():
        builder.row(InlineKeyboardButton(text=label, callback_data=f"{_CALLBACK_MODEL_PREFIX}{model_id}"))
    builder.row(InlineKeyboardButton(text="✖️ Закрыть", callback_data=_CALLBACK_CANCEL))
    return builder.as_markup()


def _size_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="2K", callback_data=f"{_CALLBACK_SIZE_PREFIX}2K"),
                InlineKeyboardButton(text="4K", callback_data=f"{_CALLBACK_SIZE_PREFIX}4K"),
            ],
            [InlineKeyboardButton(text="✖️ Отменить тест", callback_data=_CALLBACK_CANCEL)],
        ]
    )


def _cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✖️ Отменить тест", callback_data=_CALLBACK_CANCEL)]]
    )


def install_admin_test_menu_button() -> None:
    """Append the test entry to the main menu only for configured admins."""
    from bot import keyboards

    current = keyboards.get_main_menu_keyboard
    if getattr(current, "__nexus_admin_test_installed__", False):
        return

    def wrapped_main_menu_keyboard(
        user_credits: int = 0,
        telegram_id: int | None = None,
        mini_app_referral_code: str | None = None,
    ) -> InlineKeyboardMarkup:
        markup = current(
            user_credits=user_credits,
            telegram_id=telegram_id,
            mini_app_referral_code=mini_app_referral_code,
        )
        if not _is_admin(telegram_id):
            return markup
        return InlineKeyboardMarkup(
            inline_keyboard=[
                *markup.inline_keyboard,
                [InlineKeyboardButton(text="🧪 Тест", callback_data=_CALLBACK_OPEN)],
            ]
        )

    wrapped_main_menu_keyboard.__nexus_admin_test_installed__ = True
    keyboards.get_main_menu_keyboard = wrapped_main_menu_keyboard


async def _json_response(response: aiohttp.ClientResponse) -> dict[str, Any]:
    try:
        payload = await response.json(content_type=None)
    except Exception as exc:
        body = (await response.text())[:1000]
        raise RuntimeError(f"NexusAPI вернул не-JSON ответ ({response.status}): {body}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"NexusAPI вернул неожиданный JSON: {type(payload).__name__}")
    return payload


async def _start_task(session: aiohttp.ClientSession, settings: NexusSettings, params: dict[str, Any]) -> str:
    async with session.post(
        f"{settings.base_url}/generate",
        headers={"Authorization": f"Bearer {settings.api_key}"},
        json={"params": params},
    ) as response:
        payload = await _json_response(response)
        if response.status != 202:
            detail = payload.get("detail") or payload.get("error") or payload
            raise RuntimeError(f"Запуск задачи отклонён: HTTP {response.status}: {detail}")
        task_id = str(payload.get("task_id") or "").strip()
        if not task_id:
            raise RuntimeError("NexusAPI не вернул task_id")
        return task_id


async def _wait_for_task(
    session: aiohttp.ClientSession,
    settings: NexusSettings,
    task_id: str,
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + settings.timeout_seconds
    while loop.time() < deadline:
        async with session.get(
            f"{settings.base_url}/tasks/{task_id}",
            headers={"Authorization": f"Bearer {settings.api_key}"},
        ) as response:
            payload = await _json_response(response)
            if response.status != 200:
                detail = payload.get("detail") or payload.get("error") or payload
                raise RuntimeError(f"Проверка задачи не удалась: HTTP {response.status}: {detail}")
        status = str(payload.get("status") or "").lower()
        if status in _TERMINAL_STATUSES:
            if status == "failed":
                raise RuntimeError(str(payload.get("error") or "NexusAPI сообщил об ошибке генерации"))
            return payload
        await asyncio.sleep(settings.poll_interval_seconds)
    raise TimeoutError(f"NexusAPI не завершил задачу за {settings.timeout_seconds} секунд")


def _extract_image_result(payload: dict[str, Any]) -> tuple[str, str]:
    result = payload.get("result")
    if isinstance(result, str) and result.strip():
        value = result.strip()
        return ("url", value) if value.startswith(("http://", "https://")) else ("base64", value)
    if not isinstance(result, dict):
        raise RuntimeError("В completed-ответе NexusAPI отсутствует result")

    for key in ("image_url", "url"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return "url", value.strip()

    images = result.get("images") or result.get("image_urls")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, str) and first.strip():
            value = first.strip()
            return ("url", value) if value.startswith(("http://", "https://")) else ("base64", value)
        if isinstance(first, dict):
            for key in ("image_url", "url", "base64", "b64_json"):
                value = first.get(key)
                if isinstance(value, str) and value.strip():
                    return ("url", value.strip()) if value.startswith(("http://", "https://")) else ("base64", value.strip())

    for key in ("base64", "b64_json", "image_base64"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return "base64", value.strip()
    raise RuntimeError("Не удалось найти изображение в результате NexusAPI")


def _decode_base64_image(value: str) -> bytes:
    encoded = value.split(",", 1)[1] if value.startswith("data:") and "," in value else value
    try:
        return base64.b64decode(encoded, validate=False)
    except Exception as exc:
        raise RuntimeError("NexusAPI вернул повреждённое base64-изображение") from exc


async def _telegram_photo_as_data_url(message: types.Message) -> str | None:
    if not message.photo:
        return None
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    buffer = await message.bot.download_file(file.file_path)
    raw = buffer.read()
    return f"data:image/jpeg;base64,{base64.b64encode(raw).decode('ascii')}"


async def _ask_for_input(callback: types.CallbackQuery, state: FSMContext, model_id: str) -> None:
    data = await state.get_data()
    image_size = str(data.get("nexus_image_size") or "")
    await state.set_state(NexusAdminTestState.waiting_for_input)
    size_line = f"\nРазрешение: <b>{image_size}</b>" if image_size else ""
    await callback.message.answer(
        f"Выбрана <b>{_ALLOWED_MODELS[model_id]}</b>.{size_line}\n\n"
        "Отправьте текстовый промпт или фото с промптом в подписи. "
        "Фото будет передано как референс через <code>image_urls</code>.",
        reply_markup=_cancel_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == _CALLBACK_OPEN)
async def open_nexus_test(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступно только администраторам", show_alert=True)
        return
    await state.clear()
    settings = NexusSettings.from_env()
    if not settings.api_key:
        await callback.message.answer(
            "🧪 <b>NexusAPI тест</b>\n\n"
            "Не задан <code>NEXUS_API_KEY</code>. Добавьте ключ в env контейнера и передеплойте.",
            parse_mode="HTML",
        )
        await callback.answer()
        return
    await callback.message.answer(
        "🧪 <b>NexusAPI: выбор модели</b>\n\n"
        "Тестовый контур не списывает бананы и не публикует результат в ленту.",
        reply_markup=_model_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith(_CALLBACK_MODEL_PREFIX))
async def choose_nexus_model(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступно только администраторам", show_alert=True)
        return
    model_id = str(callback.data).removeprefix(_CALLBACK_MODEL_PREFIX)
    if model_id not in _ALLOWED_MODELS:
        await callback.answer("Неизвестная модель", show_alert=True)
        return
    await state.update_data(nexus_model_id=model_id)
    if model_id in _SIZE_MODELS:
        await state.set_state(NexusAdminTestState.waiting_for_size)
        await callback.message.answer(
            f"Выбрана <b>{_ALLOWED_MODELS[model_id]}</b>.\n\nВыберите разрешение результата:",
            reply_markup=_size_keyboard(),
            parse_mode="HTML",
        )
    else:
        await state.update_data(nexus_image_size=None)
        await _ask_for_input(callback, state, model_id)
    await callback.answer()


@router.callback_query(NexusAdminTestState.waiting_for_size, F.data.startswith(_CALLBACK_SIZE_PREFIX))
async def choose_nexus_size(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступно только администраторам", show_alert=True)
        return
    image_size = str(callback.data).removeprefix(_CALLBACK_SIZE_PREFIX).upper()
    if image_size not in _ALLOWED_SIZES:
        await callback.answer("Неизвестное разрешение", show_alert=True)
        return
    data = await state.get_data()
    model_id = str(data.get("nexus_model_id") or "")
    if model_id not in _SIZE_MODELS:
        await state.clear()
        await callback.answer("Тестовая сессия устарела", show_alert=True)
        return
    await state.update_data(nexus_image_size=image_size)
    await _ask_for_input(callback, state, model_id)
    await callback.answer()


@router.callback_query(F.data == _CALLBACK_CANCEL)
async def cancel_nexus_test(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступно только администраторам", show_alert=True)
        return
    await state.clear()
    await callback.message.answer("Тест NexusAPI отменён.")
    await callback.answer()


@router.message(NexusAdminTestState.waiting_for_input, F.text | F.photo)
async def run_nexus_test(message: types.Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await state.clear()
        return

    prompt = (message.text or message.caption or "").strip()
    if not prompt:
        await message.answer("Добавьте промпт текстом или в подписи к фото.")
        return

    data = await state.get_data()
    model_id = str(data.get("nexus_model_id") or "")
    image_size = str(data.get("nexus_image_size") or "")
    if model_id not in _ALLOWED_MODELS:
        await state.clear()
        await message.answer("Тестовая сессия устарела. Откройте кнопку «Тест» заново.")
        return

    settings = NexusSettings.from_env()
    if not settings.api_key:
        await state.clear()
        await message.answer("Не задан NEXUS_API_KEY в окружении контейнера.")
        return

    params: dict[str, Any] = {"model_name": model_id, "prompt": prompt}
    if model_id in _SIZE_MODELS and image_size in _ALLOWED_SIZES:
        params["image_size"] = image_size

    image_data_url = await _telegram_photo_as_data_url(message)
    if image_data_url:
        # Nexus Nano Banana schemas require a list, even for one reference.
        params["image_urls"] = [image_data_url]

    await state.clear()
    ref_line = "\nРеференсов: <b>1</b>" if image_data_url else ""
    size_line = f"\nРазрешение: <b>{image_size}</b>" if image_size else ""
    progress = await message.answer(
        f"⏳ Запускаю <b>{_ALLOWED_MODELS[model_id]}</b>…{size_line}{ref_line}",
        parse_mode="HTML",
    )

    timeout = aiohttp.ClientTimeout(total=settings.timeout_seconds + 30, connect=15, sock_read=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            task_id = await _start_task(session, settings, params)
            await progress.edit_text(
                f"⏳ Задача <code>{task_id}</code> выполняется в NexusAPI…{size_line}{ref_line}",
                parse_mode="HTML",
            )
            payload = await _wait_for_task(session, settings, task_id)
        result_type, result_value = _extract_image_result(payload)
        caption = (
            "✅ <b>NexusAPI тест завершён</b>\n"
            f"Модель: <code>{model_id}</code>\n"
            f"Разрешение: <code>{image_size or 'provider default'}</code>\n"
            f"Референсов передано: <code>{1 if image_data_url else 0}</code>\n"
            f"Task ID: <code>{task_id}</code>"
        )
        if result_type == "url":
            await message.answer_photo(result_value, caption=caption, parse_mode="HTML")
        else:
            await message.answer_photo(
                BufferedInputFile(_decode_base64_image(result_value), filename=f"nexus-{task_id}.png"),
                caption=caption,
                parse_mode="HTML",
            )
        await progress.delete()
    except (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError, RuntimeError) as exc:
        logger.warning(
            "NexusAPI admin test failed: admin=%s model=%s error=%s",
            message.from_user.id if message.from_user else None,
            model_id,
            exc,
        )
        await progress.edit_text(
            "❌ <b>NexusAPI тест не завершён</b>\n\n"
            f"<code>{str(exc)[:1500]}</code>",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception(
            "Unexpected NexusAPI admin test failure: admin=%s model=%s",
            message.from_user.id if message.from_user else None,
            model_id,
        )
        await progress.edit_text("❌ Непредвиденная ошибка тестового контура NexusAPI. Подробности в логах.")
