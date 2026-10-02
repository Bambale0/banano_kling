"""Private admin-only Gemini image lab; persistent settings and result recovery."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from aiogram import F, Router, types
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.database import get_bot_setting, set_bot_setting
from bot.handlers.generation import (
    _persist_reusable_media_reference,
    _save_reference_image_from_message,
)
from bot.services.openrouter_image_service import (
    MODEL,
    ImageProviderError,
    openrouter_image_service,
)

router = Router(name="admin_gemini_image_lab")
logger = logging.getLogger(__name__)
OUTPUT_ROOT = Path("outputs/admin-gemini-image")
_LOCKS: dict[int, asyncio.Lock] = {}
_TASKS: set[asyncio.Task] = set()
_FIELDS = ("prompt", "references", "provider", "ratio", "resolution", "timeout")


class GeminiImageLabStates(StatesGroup):
    prompt = State()
    references = State()


def _lock(admin_id: int) -> asyncio.Lock:
    return _LOCKS.setdefault(admin_id, asyncio.Lock())


async def load_session(admin_id: int) -> dict[str, Any]:
    value = await get_bot_setting(f"gemini_image_lab:{admin_id}")
    if value:
        data = json.loads(value)
        data.setdefault(
            "last_success", data["job"] if data["job"].get("status") == "ready" else {}
        )
        return data
    return {
        "prompt": "",
        "references": [],
        "provider": "auto",
        "ratio": "auto",
        "resolution": "1K",
        "timeout": 240,
        "nonce": uuid.uuid4().hex[:16],
        "job": {},
        "last_success": {},
    }


async def save_session(admin_id: int, data: dict[str, Any]) -> None:
    if not await set_bot_setting(
        f"gemini_image_lab:{admin_id}",
        json.dumps(data),
        updated_by_telegram_id=admin_id,
    ):
        raise RuntimeError("Unable to persist admin image lab session")


def _keyboard(rows: list[list[tuple[str, str]]]):
    builder = InlineKeyboardBuilder()
    for row in rows:
        builder.row(
            *[
                types.InlineKeyboardButton(
                    text=text, callback_data=f"admin_gmi:{action}"
                )
                for text, action in row
            ]
        )
    return builder.as_markup()


def _back():
    return _keyboard([[("⬅️ Настройки", "open")]])


async def _show(message: types.Message, text: str, markup, *, edit: bool = True):
    if edit:
        try:
            await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
            return
        except TelegramAPIError:
            pass
    await message.answer(text, reply_markup=markup, parse_mode="HTML")


async def _dashboard(
    message: types.Message, data: dict[str, Any], *, edit: bool = True
):
    prompt = html.escape(data["prompt"][:600] or "не задан")
    job = data["job"]
    status = {
        "running": "⏳ выполняется",
        "ready": "✅ готов",
        "error": "❌ ошибка",
        "unknown": "⚠️ исход неизвестен",
    }.get(job.get("status"), "ещё нет")
    provider = "Авто" if data["provider"] == "auto" else data["provider"]
    text = (
        f"🧪 <b>Gemini 3 Pro Image · OpenRouter</b>\n"
        f"Nano Banana Pro · {'Фото → фото' if data['references'] else 'Текст → фото'}\n\n"
        f"Провайдер: <b>{html.escape(provider)}</b>\n"
        f"Формат: <b>{html.escape(data['ratio'])}</b> · Разрешение: <b>{html.escape(data['resolution'])}</b>\n"
        f"Референсы: <b>{len(data['references'])}</b> · Ожидание: {data['timeout']} сек.\n"
        f"Последний запрос: {status}\n\nПромпт: <i>{prompt}</i>\n\n"
        "Бананы не списываются. Используется платный аккаунт OpenRouter.\n"
        "Задайте промпт, при необходимости добавьте изображения и нажмите «Создать»."
    )
    if not openrouter_image_service.enabled:
        text += "\n\n⚠️ Ключ OpenRouter не настроен на сервере."
    if job.get("error"):
        text += "\n\n" + html.escape(job["error"])
    rows = [
        [("✍️ Промпт", "prompt"), (f"🖼 Референсы ({len(data['references'])})", "refs")],
        [("↔️ Формат", "ratios"), ("✨ Разрешение", "resolutions")],
        [("🌐 Провайдер", "providers"), ("⏱ Ожидание", "timeouts")],
    ]
    if job.get("status") == "running":
        rows.append([("🔄 Статус", "open")])
    else:
        rows.append([("🚀 Создать", f"generate:{data['nonce']}")])
    if data["last_success"]:
        rows.extend(
            [
                [("📥 Получить результат", "result"), ("✏️ Доработать", "edit")],
                [("🔁 Повторить запрос", f"repeat:{data['nonce']}")],
            ]
        )
    rows.append([("ℹ️ Возможности", "info")])
    markup = _keyboard(rows)
    markup.inline_keyboard.append(
        [
            types.InlineKeyboardButton(
                text="⬅️ В тесты", callback_data="admin_test_lab"
            ),
            types.InlineKeyboardButton(
                text="🏠 Главное меню", callback_data="back_main"
            ),
        ]
    )
    await _show(message, text, markup, edit=edit)


def _job_path(job: dict[str, Any], filename: str) -> Path:
    # Both values originate from our persistence, still fail closed on invalid paths.
    request_id = str(uuid.UUID(job["id"]))
    if Path(filename).name != filename:
        raise ValueError("Invalid result filename")
    return OUTPUT_ROOT / request_id / filename


async def _deliver(bot, admin_id: int, job: dict[str, Any]) -> None:
    if not config.is_admin(admin_id):
        return
    cost = job.get("usage", {}).get("cost")
    cost_text = (
        f"\nРасход OpenRouter: ${float(cost):.6f}"
        if isinstance(cost, (int, float))
        else ""
    )
    caption = (
        f"✅ Gemini 3 Pro Image · {job['settings']['resolution']}\n"
        f"Время: {job['elapsed']:.1f} сек.{cost_text}\nID: {job['id']}"
    )
    for filename in job["files"]:
        path = _job_path(job, filename)
        try:
            await bot.send_photo(
                chat_id=admin_id, photo=FSInputFile(path), caption=caption
            )
        except TelegramAPIError:
            pass  # Original document below is also supported for large 4K images.
        await bot.send_document(
            chat_id=admin_id,
            document=FSInputFile(path),
            caption="Оригинал без сжатия\n" + caption,
            reply_markup=_back(),
        )
    logger.info(
        "gemini_image_lab delivered admin_id=%s request_id=%s", admin_id, job["id"]
    )


async def _run(
    bot, admin_id: int, job: dict[str, Any], capabilities: list[dict[str, Any]]
) -> None:
    started = time.monotonic()
    try:
        result = await openrouter_image_service.generate(
            capabilities=capabilities, **job["settings"]
        )
        directory = OUTPUT_ROOT / job["id"]
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        files = []
        for index, image in enumerate(result.images):
            filename = f"{index + 1}.{image.extension}"
            path = directory / filename
            await asyncio.to_thread(path.write_bytes, image.data)
            path.chmod(0o600)
            files.append(filename)
        job.update(
            status="ready",
            files=files,
            provider_id=result.request_id,
            usage=result.usage,
            elapsed=time.monotonic() - started,
        )
    except (ImageProviderError, ValueError, OSError) as exc:
        job.update(
            status="error",
            error=str(exc)
            if isinstance(exc, (ImageProviderError, ValueError))
            else "Не удалось сохранить результат. Проверьте статус OpenRouter перед новым запуском.",
        )
        logger.warning(
            "gemini_image_lab failed admin_id=%s request_id=%s error_type=%s error_code=%s elapsed=%.1f",
            admin_id,
            job["id"],
            type(exc).__name__,
            getattr(exc, "code", "local_storage_or_validation"),
            time.monotonic() - started,
        )
    # Persist before delivery, independent of the current FSM/menu.
    async with _lock(admin_id):
        data = await load_session(admin_id)
        if data["job"].get("id") != job["id"]:
            return
        data["job"] = job
        if job["status"] == "ready":
            data["last_success"] = job
        await save_session(admin_id, data)
    logger.info(
        "gemini_image_lab completed admin_id=%s request_id=%s provider_id=%s status=%s elapsed=%.1f",
        admin_id,
        job["id"],
        job.get("provider_id", ""),
        job["status"],
        time.monotonic() - started,
    )
    if not config.is_admin(admin_id):
        return
    try:
        if job["status"] == "ready":
            await _deliver(bot, admin_id, job)
        else:
            await bot.send_message(admin_id, job["error"], reply_markup=_back())
    except (TelegramAPIError, OSError):
        logger.warning(
            "gemini_image_lab delivery_failed admin_id=%s request_id=%s",
            admin_id,
            job["id"],
        )


def _start(coro):
    task = asyncio.create_task(coro)
    _TASKS.add(task)

    def completed(done):
        _TASKS.discard(done)
        if not done.cancelled() and done.exception():
            logger.error(
                "gemini_image_lab background_failed error_type=%s",
                type(done.exception()).__name__,
            )

    task.add_done_callback(completed)


async def _references_screen(message, data, caps, *, edit=True):
    maximum = openrouter_image_service.options(caps, data["provider"])["max_references"]
    rows = [[("✅ Готово", "open")]]
    if data["references"]:
        rows.append([("↩️ Удалить последний", "refs_pop"), ("🗑 Очистить", "refs_clear")])
    rows.append([("⬅️ Настройки", "open")])
    await _show(
        message,
        f"🖼 <b>Референсы: {len(data['references'])}/{maximum}</b>\n\n"
        "Отправьте фото или файлы PNG, JPEG, WEBP, в том числе альбомом. "
        "Файл — до 20 МБ. Лучше отправлять файлом для сохранения качества. "
        "Порядок изображений соответствует порядку загрузки.",
        _keyboard(rows),
        edit=edit,
    )


@router.callback_query(F.data.startswith("admin_gmi:"))
async def handle_callback(callback: types.CallbackQuery, state: FSMContext):
    admin_id = callback.from_user.id
    if not config.is_admin(admin_id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    if not callback.message or callback.message.chat.type != "private":
        await callback.answer("Откройте тест в личном чате с ботом.", show_alert=True)
        return
    await callback.answer()
    parts = callback.data.split(":", 2)
    action, value = parts[1], parts[2] if len(parts) > 2 else ""
    async with _lock(admin_id):
        data = await load_session(admin_id)
        job = data["job"]
        if (
            job.get("status") == "running"
            and time.time() > job["started"] + job["settings"]["timeout"] + 60
        ):
            job.update(
                status="unknown",
                error="Ожидание прервано или бот перезапущен. Проверьте OpenRouter Activity перед новым запросом.",
            )
        try:
            if action == "open":
                await state.set_state(None)
            elif action == "prompt":
                await state.set_state(GeminiImageLabStates.prompt)
                await callback.message.answer(
                    "✍️ Отправьте промпт. Сообщения добавляются по порядку. "
                    "Чтобы заменить текст, сначала нажмите «Очистить».",
                    reply_markup=_keyboard(
                        [[("✅ Готово", "open"), ("🗑 Очистить", "prompt_clear")]]
                    ),
                )
                return
            elif action == "prompt_clear":
                data["prompt"] = ""
                await state.set_state(GeminiImageLabStates.prompt)
            elif action in ("refs", "refs_clear", "refs_pop"):
                caps = await openrouter_image_service.capabilities()
                if action == "refs_clear":
                    data["references"] = []
                elif action == "refs_pop":
                    data["references"] = data["references"][:-1]
                await save_session(admin_id, data)
                await state.set_state(GeminiImageLabStates.references)
                await _references_screen(callback.message, data, caps)
                return
            elif action in ("ratios", "resolutions", "providers", "timeouts"):
                caps = await openrouter_image_service.capabilities(
                    refresh=action == "providers"
                )
                options = openrouter_image_service.options(
                    caps, "auto" if action == "providers" else data["provider"]
                )
                choices = {
                    "ratios": [("Авто", "ratio:auto")]
                    + [(v, f"ratio:{v}") for v in options["aspect_ratio"]],
                    "resolutions": [
                        (v, f"resolution:{v}") for v in options["resolution"]
                    ],
                    "providers": [("Авто (доступные)", "provider:auto")]
                    + [
                        (e["provider_name"], f"provider:{e['provider_tag']}")
                        for e in caps
                    ],
                    "timeouts": [
                        (f"{v} сек.", f"timeout:{v}") for v in (120, 240, 480)
                    ],
                }[action]
                await state.set_state(None)
                await _show(
                    callback.message,
                    "Выберите параметр:",
                    _keyboard(
                        [choices[i : i + 2] for i in range(0, len(choices), 2)]
                        + [[("⬅️ Настройки", "open")]]
                    ),
                )
                return
            elif action in ("ratio", "resolution", "provider", "timeout"):
                caps = await openrouter_image_service.capabilities()
                options = openrouter_image_service.options(
                    caps, "auto" if action == "provider" else data["provider"]
                )
                allowed = {
                    "ratio": ["auto"] + options["aspect_ratio"],
                    "resolution": options["resolution"],
                    "provider": ["auto"] + [e["provider_tag"] for e in caps],
                    "timeout": ["120", "240", "480"],
                }[action]
                if value not in allowed:
                    raise ValueError("Параметр устарел. Откройте настройки заново.")
                data[action] = int(value) if action == "timeout" else value
                if action == "provider":
                    options = openrouter_image_service.options(caps, value)
                    if data["resolution"] not in options["resolution"]:
                        data["resolution"] = options["resolution"][0]
                    if data["ratio"] not in options["aspect_ratio"]:
                        data["ratio"] = "auto"
                await state.set_state(None)
            elif action in ("generate", "repeat"):
                if value != data["nonce"]:
                    raise ValueError(
                        "Эта кнопка уже использована. Настройки обновлены; для нового запроса нажмите «Создать»."
                    )
                if job.get("status") == "running":
                    raise ValueError("Запрос уже выполняется. Дождитесь результата.")
                if not openrouter_image_service.enabled:
                    raise ImageProviderError("Ключ OpenRouter не настроен на сервере.")
                settings = {key: data[key] for key in _FIELDS}
                if action == "repeat":
                    if not data["last_success"]:
                        raise ValueError("Нет готового запроса для повтора.")
                    settings = dict(data["last_success"]["settings"])
                caps = await openrouter_image_service.capabilities()
                openrouter_image_service.build_payload(
                    capabilities=caps,
                    **{k: v for k, v in settings.items() if k != "timeout"},
                )
                job = {
                    "id": str(uuid.uuid4()),
                    "started": time.time(),
                    "status": "running",
                    "settings": settings,
                }
                data.update(job=job, nonce=uuid.uuid4().hex[:16])
                await save_session(admin_id, data)
                await state.set_state(None)
                logger.info(
                    "gemini_image_lab submitted admin_id=%s request_id=%s model=%s provider=%s references=%s resolution=%s",
                    admin_id,
                    job["id"],
                    MODEL,
                    settings["provider"],
                    len(settings["references"]),
                    settings["resolution"],
                )
                _start(_run(callback.bot, admin_id, job, caps))
            elif action == "result":
                job = data["last_success"]
                if job.get("status") != "ready":
                    raise ValueError("Готового результата пока нет.")
                await _deliver(callback.bot, admin_id, job)
                return
            elif action == "edit":
                job = data["last_success"]
                if job.get("status") != "ready":
                    raise ValueError("Сначала создайте изображение.")
                path = _job_path(job, job["files"][0])
                url = await _persist_reusable_media_reference(
                    admin_id,
                    await asyncio.to_thread(path.read_bytes),
                    path.suffix.lstrip("."),
                    kind="image",
                    original_filename=path.name,
                    content_type="image/jpeg"
                    if path.suffix == ".jpg"
                    else f"image/{path.suffix[1:]}",
                )
                if not url:
                    raise ValueError(
                        "Не удалось подготовить результат для правки. Попробуйте ещё раз."
                    )
                data.update(references=[url], prompt="")
                await save_session(admin_id, data)
                await state.set_state(GeminiImageLabStates.prompt)
                await callback.message.answer(
                    "✏️ Результат добавлен как референс. Напишите, что изменить, "
                    "затем нажмите «Готово» и «Создать».",
                    reply_markup=_back(),
                )
                return
            elif action == "info":
                caps = await openrouter_image_service.capabilities(refresh=True)
                options = openrouter_image_service.options(caps, data["provider"])
                await _show(
                    callback.message,
                    "<b>Gemini 3 Pro Image / Nano Banana Pro</b>\n\n"
                    f"Генерация по тексту, редактирование и объединение до {options['max_references']} изображений. "
                    "Один результат за запуск. Повтор создаёт новый вариант, «Доработать» использует результат как референс.\n\n"
                    f"Разрешения выбранного провайдера: {html.escape(', '.join(options['resolution']))}. "
                    "Параметры загружаются из OpenRouter. Авто выбирает только провайдеров, поддерживающих ваши настройки.\n\n"
                    "Для текста на изображении, коллажей, света, ракурса и локальных правок используйте промпт. "
                    "Отдельные маски, прозрачный фон, seed и веб-поиск этим Image API не заявлены.\n\n"
                    "Настройки и последний результат сохраняются. При сбое доставки используйте «Получить результат». "
                    "Запросы не повторяются автоматически, чтобы избежать лишних расходов.",
                    _back(),
                )
                return
            else:
                raise ValueError("Кнопка устарела. Откройте тест заново.")
            await save_session(admin_id, data)
            await _dashboard(callback.message, data)
        except (ImageProviderError, ValueError) as exc:
            await callback.message.answer(
                html.escape(str(exc)), parse_mode="HTML", reply_markup=_back()
            )
        except (OSError, TelegramAPIError):
            logger.warning(
                "gemini_image_lab action_failed admin_id=%s action=%s", admin_id, action
            )
            await callback.message.answer(
                "Не удалось получить или отправить файл. Откройте настройки и повторите.",
                reply_markup=_back(),
            )


@router.message(GeminiImageLabStates.prompt)
@router.message(GeminiImageLabStates.references)
async def receive_message(message: types.Message, state: FSMContext):
    if not message.from_user or not config.is_admin(message.from_user.id):
        await state.clear()
        return
    if message.chat.type != "private":
        return
    admin_id = message.from_user.id
    async with _lock(admin_id):
        data = await load_session(admin_id)
        try:
            if await state.get_state() == GeminiImageLabStates.prompt.state:
                if not message.text or message.text.startswith("/"):
                    await message.answer(
                        "Отправьте текст промпта.", reply_markup=_back()
                    )
                    return
                prompt = "\n".join(filter(None, [data["prompt"], message.text.strip()]))
                if len(prompt) > 20000:
                    raise ValueError(
                        "Промпт тестового контура ограничен 20 000 символами. Сократите текст."
                    )
                data["prompt"] = prompt
                await save_session(admin_id, data)
                await message.answer(
                    f"✅ Промпт сохранён ({len(prompt)} символов). "
                    "Можно добавить текст или вернуться к настройкам.",
                    reply_markup=_back(),
                )
            elif await state.get_state() == GeminiImageLabStates.references.state:
                caps = await openrouter_image_service.capabilities()
                maximum = openrouter_image_service.options(caps, data["provider"])[
                    "max_references"
                ]
                if len(data["references"]) >= maximum:
                    raise ValueError(f"Достигнут лимит: {maximum} референсов.")
                media = message.photo[-1] if message.photo else message.document
                if media and media.file_size and media.file_size > 20 * 1024 * 1024:
                    raise ValueError("Файл больше 20 МБ. Отправьте уменьшенную копию.")
                url, error = await _save_reference_image_from_message(
                    message, original_filename_prefix="gemini-image-lab"
                )
                if error or not url:
                    raise ValueError(error or "Не удалось сохранить референс.")
                if url not in data["references"]:
                    data["references"].append(url)
                if (
                    message.caption
                    and len(data["prompt"]) + len(message.caption) + 1 <= 20000
                ):
                    data["prompt"] = "\n".join(
                        filter(None, [data["prompt"], message.caption])
                    )
                await save_session(admin_id, data)
                await _references_screen(message, data, caps, edit=False)
        except (ImageProviderError, ValueError) as exc:
            await message.answer(str(exc), reply_markup=_back())
