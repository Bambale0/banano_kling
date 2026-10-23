"""Telegram editor for the same typed admin-only Kling4 recipes as Mini App."""

from __future__ import annotations

import asyncio
import html
import logging
import uuid
import weakref
from functools import wraps

from aiogram import F, Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.services.kling4_contract import RATIOS, Kling4Error, require_admin
from bot.services.kling4_lifecycle import kling4_lifecycle
from bot.services.wan3_prime_media import Wan3PrimeValidationError

from .kling4_automatic import AutomaticComposer

router = Router(name="kling4")
logger = logging.getLogger(__name__)
automatic_composer = AutomaticComposer()


_ACTOR_LOCKS: weakref.WeakValueDictionary[tuple[int, int], asyncio.Lock] = (
    weakref.WeakValueDictionary()
)


def actor_lock(event, state):
    key = (state.key.bot_id, event.from_user.id)
    lock = _ACTOR_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _ACTOR_LOCKS[key] = lock
    return lock


def serialized(handler):
    @wraps(handler)
    async def wrapped(event, state, **_context):
        async with actor_lock(event, state):
            return await handler(event, state)

    return wrapped


class Kling4States(StatesGroup):
    editing = State()
    text = State()
    media = State()


def serialized_text(handler):
    @wraps(handler)
    async def wrapped(message, state, **_context):
        # StateFilter ran before this handler could wait for a navigation callback.
        initial = await state.get_data()
        expected = initial.get("k4_text_session")
        field = initial.get("k4_field")
        async with actor_lock(message, state):
            current = await state.get_data()
            if (
                await state.get_state() != Kling4States.text.state
                or not isinstance(field, str)
                or current.get("k4_field") != field
                or current.get("k4_text_session") != expected
            ):
                return
            if field != "prompt":
                return await handler(message, state)
            if not await admin(message):
                return
            # A prompt field opened before this release uses the same intake
            # readiness checks as new editing-state messages.
            await state.set_state(Kling4States.editing)
            await state.update_data(k4_field=None, k4_text_session=None)
        return await automatic_composer.handle(message, state)

    return wrapped


def fresh():
    return {
        "mode": "reference",
        "input": {
            "prompt": "",
            "duration": 5,
            "resolution": "720p",
            "aspect_ratio": "auto",
        },
    }


async def admin(event):
    if config.is_admin(event.from_user.id):
        return True
    if isinstance(event, types.CallbackQuery):
        await event.answer("Доступно только администратору.", show_alert=True)
    else:
        await event.answer("Доступно только администратору.")
    return False


async def actor(telegram_id):
    from bot.wan3_prime_api import _telegram_actor

    value = await _telegram_actor(telegram_id)
    require_admin(value)
    return value


def get_path(recipe, path):
    value = recipe["input"]
    for part in path.split("."):
        value = value[int(part)] if part.isdigit() else value.get(part)
    return value


def set_path(recipe, path, value):
    parts = path.split(".")
    target = recipe["input"]
    for part in parts[:-1]:
        target = target[int(part)] if part.isdigit() else target[part]
    if value is None:
        target.pop(parts[-1], None)
    else:
        target[parts[-1]] = value


def navigation(builder=None, *, back="k4:done", back_label="← В редактор"):
    b = builder if builder is not None else InlineKeyboardBuilder()
    if back:
        b.row(types.InlineKeyboardButton(text=back_label, callback_data=back))
    b.row(
        types.InlineKeyboardButton(
            text="← Kling", callback_data="video_models:kling:0"
        ),
        types.InlineKeyboardButton(
            text="Все модели", callback_data="video_models:all:0"
        ),
    )
    return b.as_markup()


def field_parent(path):
    parts = path.split(".")
    if len(parts) == 3 and parts[0] in {"elements", "voices"}:
        kind = "element" if parts[0] == "elements" else "voice"
        return f"k4:{kind}:{parts[1]}"
    return "k4:done"


def mode_label(recipe):
    return "Референсы" if recipe["mode"] == "reference" else "По кадрам"


async def materials_menu(message, recipe):
    data = recipe["input"]
    b = InlineKeyboardBuilder()
    b.button(text="+ Персонаж / объект по фото", callback_data="k4:new:image")
    b.button(text="+ Персонаж по видео", callback_data="k4:new:video")
    b.button(text="+ Голос", callback_data="k4:new:voice")
    for i, item in enumerate(data.get("elements", [])):
        b.button(text=f"Материал @{item['name']}", callback_data=f"k4:element:{i}")
    for i, item in enumerate(data.get("voices", [])):
        b.button(text=f"Голос @{item['name']}", callback_data=f"k4:voice:{i}")
    b.adjust(1)
    await message.answer(
        "Персонажи, объекты и голоса\nДобавьте материал, затем откройте его для загрузки файлов. Используйте @имя в промпте.",
        reply_markup=navigation(b),
    )


def keyboard(recipe):
    b = InlineKeyboardBuilder()
    data = recipe["input"]
    ratio = data.get("aspect_ratio", "auto")
    for values in (("auto",), RATIOS[1:4], RATIOS[4:]):
        b.row(
            *[
                types.InlineKeyboardButton(
                    text=("✅ " if ratio == value else "")
                    + ("Авто" if value == "auto" else value),
                    callback_data="k4:ratio:" + value,
                )
                for value in values
            ]
        )
    b.row(
        types.InlineKeyboardButton(text="− 1с", callback_data="k4:duration:-1"),
        types.InlineKeyboardButton(
            text=f"⏱ {data['duration']}с", callback_data="k4:duration:0"
        ),
        types.InlineKeyboardButton(text="+ 1с", callback_data="k4:duration:1"),
    )
    b.row(types.InlineKeyboardButton(text="Очистить медиа", callback_data="k4:clear"))
    b.row(
        types.InlineKeyboardButton(
            text="К моделям", callback_data="video_models:kling:0"
        )
    )
    return b.as_markup()


async def show(message, state):
    data = await state.get_data()
    recipe = data.get("k4_recipe", fresh())
    inp = recipe["input"]
    await state.set_state(Kling4States.editing)
    await state.update_data(k4_field=None, k4_media_session=None, k4_text_session=None)
    await message.answer(
        "<b>Kling 4 · администратор</b>\n"
        + f"{mode_label(recipe)} · {inp['duration']}с · {inp['resolution']}\n"
        + "Отправьте фото, видео или аудио — бот сам добавит референсы.\n"
        + "Отправка промпта сразу запускает генерацию.\n"
        + html.escape(inp["prompt"] or "")
        + "\nБананы не списываются.",
        parse_mode="HTML",
        reply_markup=keyboard(recipe),
    )


async def save(state, recipe):
    await state.update_data(k4_recipe=recipe, k4_quote=None, k4_key=uuid.uuid4().hex)


async def reset_intake(state):
    await state.update_data(
        k4_session=uuid.uuid4().hex,
        k4_auto_uploads=[],
        k4_media_messages={},
        k4_upload_errors={},
        k4_album_pending=False,
    )


async def launch_prompt(message, state, recipe):
    """Resolve the measured quote internally, preserving durable idempotency."""
    identity = await actor(message.from_user.id)
    current = await state.get_data()
    mid = getattr(message, "message_id", None)
    key = (
        f"k4_tg_{state.key.bot_id}_{state.key.chat_id}_{mid}"
        if isinstance(mid, int)
        else current["k4_key"]
    )
    quote = await kling4_lifecycle.quote(identity, recipe)
    latest = await state.get_data()
    if latest.get("k4_session") != current.get(
        "k4_session"
    ) or await state.get_state() not in {
        Kling4States.editing.state,
        Kling4States.text.state,
    }:
        return
    await state.update_data(k4_quote=quote, k4_key=key)
    result = await kling4_lifecycle.launch(identity, recipe, quote["quote_hash"], key)
    latest = await state.get_data()
    active = latest.get("k4_session") == current.get(
        "k4_session"
    ) and await state.get_state() in {
        Kling4States.editing.state,
        Kling4States.text.state,
    }
    if active:
        await state.update_data(
            k4_last_task=result["task_id"], _prompt_fragment_submit_token=None
        )
        await state.set_state(Kling4States.editing)
    logger.info(
        "Kling4 Telegram prompt submitted: telegram_id=%s task_id=%s request_id=%s status=%s",
        message.from_user.id,
        result["task_id"],
        key,
        result["status"],
    )
    status = result["status"]
    heading = (
        "Kling 4: проверяю статус запуска. Повторно отправлять этот промпт не нужно."
        if status in {"unknown", "submitting"}
        else "Kling 4: сервис отклонил запуск."
        if status == "failed"
        else "Kling 4: задача принята."
    )
    await message.answer(
        heading + "\n"
        f"{result['task_id']}\n"
        f"Расход KIE: {quote['provider_credits']} credits. Бананы: 0.\n"
        + (
            "Проверьте промпт и референсы перед следующим запуском."
            if status == "failed"
            else "Результат придёт в Telegram. Можно отправить следующий промпт."
        ),
        reply_markup=keyboard(recipe) if active else None,
    )


@router.message(Command("kling4"))
@serialized
async def command(message: types.Message, state: FSMContext):
    if not await admin(message):
        return
    await state.clear()
    await state.update_data(
        generation_type="video",
        v_model="kling_4",
        video_model_family="kling",
        video_model_page=0,
        k4_session=uuid.uuid4().hex,
    )
    await save(state, fresh())
    await show(message, state)


@router.callback_query(F.data.startswith("k4:"))
@serialized
async def callback(query: types.CallbackQuery, state: FSMContext):
    if not await admin(query):
        return
    if not query.message:
        return
    parts = query.data.split(":")
    action = parts[1]
    current = await state.get_data()
    recipe = current.get("k4_recipe", fresh())
    inp = recipe["input"]
    try:
        if action == "open":
            await state.clear()
            await state.update_data(
                generation_type="video",
                v_model="kling_4",
                video_model_family="kling",
                video_model_page=0,
                k4_session=uuid.uuid4().hex,
            )
            await save(state, fresh())
            await show(query.message, state)
        elif action == "done":
            await show(query.message, state)
        elif action == "clear":
            clean = fresh()
            clean["input"].update(
                {
                    k: inp[k]
                    for k in ("duration", "resolution", "aspect_ratio")
                    if k in inp
                }
            )
            await reset_intake(state)
            await save(state, clean)
            await show(query.message, state)
        elif action == "materials":
            if recipe["mode"] != "reference":
                raise Kling4Error("Персонажи и голоса доступны в режиме «Референсы».")
            await state.set_state(Kling4States.editing)
            await materials_menu(query.message, recipe)
        elif action == "mode":
            other = "keyframe" if recipe["mode"] == "reference" else "reference"
            # Preserve each mode draft; switching never silently discards media.
            drafts = current.get("k4_drafts", {})
            drafts[recipe["mode"]] = recipe
            await state.update_data(k4_drafts=drafts)
            next_recipe = drafts.get(
                other,
                {
                    "mode": other,
                    "input": {
                        key: inp[key]
                        for key in ("prompt", "duration", "resolution", "aspect_ratio")
                        if key in inp
                    },
                },
            )
            await save(state, next_recipe)
            await show(query.message, state)
        elif action == "duration":
            delta = int(parts[2])
            if delta not in {-1, 0, 1}:
                raise Kling4Error("Неверное изменение длительности.")
            inp["duration"] = max(3, min(30, inp["duration"] + delta))
            if delta:
                await save(state, recipe)
            await show(query.message, state)
        elif action in {"resolution", "ratio", "sound"}:
            if action == "resolution":
                inp["resolution"] = "1080p" if inp["resolution"] == "720p" else "720p"
            elif action == "ratio":
                selected = (
                    ":".join(parts[2:])
                    if len(parts) > 2
                    else RATIOS[
                        (RATIOS.index(inp.get("aspect_ratio", "auto")) + 1)
                        % len(RATIOS)
                    ]
                )
                if selected not in RATIOS:
                    raise Kling4Error("Неверный формат кадра.")
                inp["aspect_ratio"] = selected
            elif recipe["mode"] == "reference" and inp.get("video_urls"):
                inp["keep_original_sound"] = not inp.get("keep_original_sound", False)
            await save(state, recipe)
            await show(query.message, state)
        elif action == "text":
            field = parts[2]
            if field == "prompt":
                await show(query.message, state)
                await query.answer()
                return
            if field not in {"prompt", "duration"} and not field.startswith(
                ("elements.", "voices.")
            ):
                raise Kling4Error("Неверное поле.")
            await state.update_data(k4_field=field, k4_text_session=uuid.uuid4().hex)
            await state.set_state(Kling4States.text)
            await query.message.answer(
                "Отправьте "
                + (
                    "целое число секунд от 3 до 30."
                    if field == "duration"
                    else "промпт."
                    if field == "prompt"
                    else "новое значение. Для удаления необязательного поля отправьте «-»."
                ),
                reply_markup=navigation(
                    back=field_parent(field), back_label="← Отмена"
                ),
            )
        elif action == "new":
            if recipe["mode"] != "reference":
                raise Kling4Error("Персонажи и голоса доступны в режиме «Референсы».")
            kind = parts[2]
            if kind not in {"image", "video", "voice"}:
                raise Kling4Error("Неверный материал.")
            key = "voices" if kind == "voice" else "elements"
            items = inp.setdefault(key, [])
            if len(items) >= (3 if kind == "voice" else 7):
                raise Kling4Error("Лимит материалов достигнут.")
            if kind == "voice":
                item = {"name": f"Voice{len(items) + 1}", "audio_url": ""}
            else:
                item = {
                    "name": f"Hero{len(items) + 1}",
                    "tag": "character",
                    **({"image_urls": []} if kind == "image" else {"video_url": ""}),
                }
            items.append(item)
            await save(state, recipe)
            await state.set_state(Kling4States.editing)
            await materials_menu(query.message, recipe)
        elif action in {"element", "voice"}:
            index = int(parts[2])
            items = inp.get("elements" if action == "element" else "voices", [])
            if not 0 <= index < len(items):
                raise Kling4Error("Материал больше не существует.")
            item = items[index]
            prefix = ("elements" if action == "element" else "voices") + f".{index}."
            b = InlineKeyboardBuilder()
            b.button(text="Имя", callback_data="k4:text:" + prefix + "name")
            for field in (
                ("image_urls", "Фото"),
                ("video_url", "Видео"),
                ("audio_url", "Аудио"),
            ):
                if field[0] in item:
                    b.button(
                        text=field[1], callback_data="k4:media:" + prefix + field[0]
                    )
            if action == "element":
                b.button(
                    text="Описание", callback_data="k4:text:" + prefix + "description"
                )
                if item.get("tag") in (None, "character"):
                    b.button(
                        text="Привязанный голос",
                        callback_data="k4:media:" + prefix + "voice_url",
                    )
                if "image_urls" in item:
                    b.button(
                        text="Тип: " + item.get("tag", "character"),
                        callback_data=f"k4:tag:{index}",
                    )
            b.button(text="Удалить", callback_data=f"k4:remove:{action}:{index}")
            b.adjust(2)
            await state.set_state(Kling4States.editing)
            await query.message.answer(
                "Материал @" + item["name"],
                reply_markup=navigation(
                    b, back="k4:materials", back_label="← Материалы"
                ),
            )
        elif action == "tag":
            item = inp["elements"][int(parts[2])]
            tags = (
                "character",
                "animal",
                "prop",
                "costume",
                "scene",
                "effect",
                "others",
            )
            item["tag"] = tags[
                (tags.index(item.get("tag", "character")) + 1) % len(tags)
            ]
            if item["tag"] != "character":
                item.pop("voice_url", None)
            await save(state, recipe)
            await show(query.message, state)
        elif action == "remove":
            inp["elements" if parts[2] == "element" else "voices"].pop(int(parts[3]))
            await save(state, recipe)
            await show(query.message, state)
        elif action == "media":
            path = parts[2]
            # Restrict paths to the current recipe, not arbitrary state keys.
            allowed = (
                {"image_urls", "video_urls"}
                if recipe["mode"] == "reference"
                else {"first_frame_url", "keyframe_urls", "last_frame_url"}
            )
            if recipe["mode"] == "reference":
                for i, item in enumerate(inp.get("elements", [])):
                    allowed.update(
                        f"elements.{i}.{key}"
                        for key in ("image_urls", "video_url")
                        if key in item
                    )
                    if item.get("tag") in (None, "character"):
                        allowed.add(f"elements.{i}.voice_url")
                allowed.update(
                    f"voices.{i}.audio_url" for i in range(len(inp.get("voices", [])))
                )
            if path not in allowed:
                raise Kling4Error("Поле недоступно в этом режиме.")
            await state.update_data(k4_field=path, k4_media_session=uuid.uuid4().hex)
            await state.set_state(Kling4States.media)
            await media_menu(query.message, recipe, path)
        elif action in {"delete", "up"}:
            path = parts[2]
            index = int(parts[3])
            value = get_path(recipe, path)
            if isinstance(value, list):
                if action == "delete":
                    value.pop(index)
                elif index > 0:
                    value[index - 1], value[index] = value[index], value[index - 1]
            elif action == "delete":
                set_path(recipe, path, None)
            if path == "video_urls" and not inp.get("video_urls"):
                inp.pop("keep_original_sound", None)
            await save(state, recipe)
            await media_menu(query.message, recipe, path)
        elif action in {"quote", "launch"}:
            # Old message keyboards cannot bypass automatic reference readiness.
            await show(query.message, state)
        elif action == "history":
            history = await kling4_lifecycle.history(await actor(query.from_user.id))
            b = InlineKeyboardBuilder()
            for task in history[:10]:
                b.button(
                    text=task["status"] + " · " + task["task_id"][-12:],
                    callback_data="k4:task:" + task["task_id"],
                )
            b.adjust(1)
            await state.set_state(Kling4States.editing)
            await query.message.answer(
                "История Kling 4"
                if history
                else "История Kling 4 пока пуста. Создайте первое видео в редакторе.",
                reply_markup=navigation(b),
            )
        elif action == "task":
            task = await kling4_lifecycle.status(
                await actor(query.from_user.id), parts[2]
            )
            b = InlineKeyboardBuilder()
            b.button(
                text="Повторить в редакторе",
                callback_data="k4:repeat:" + task["task_id"],
            )
            if task["result_url"]:
                b.button(text="Скачать оригинал", url=task["result_url"])
            if task["status"] == "unknown":
                b.button(
                    text="Привязать ID из KIE",
                    callback_data="k4:adopt:" + task["task_id"],
                )
            b.adjust(1)
            b.row(
                types.InlineKeyboardButton(text="← История", callback_data="k4:history")
            )
            await state.set_state(Kling4States.editing)
            await query.message.answer(
                f"{task['task_id']}\n{task['status']}\nРасход KIE: {task['actual_credits'] or 'уточняется'}",
                reply_markup=navigation(b),
            )
        elif action == "repeat":
            repeat = await kling4_lifecycle.owner_recipe(
                await actor(query.from_user.id), parts[2]
            )
            await reset_intake(state)
            await save(state, repeat)
            await show(query.message, state)
        elif action == "adopt":
            await kling4_lifecycle.status(await actor(query.from_user.id), parts[2])
            await state.update_data(
                k4_adopt=parts[2], k4_field="adopt", k4_text_session=uuid.uuid4().hex
            )
            await state.set_state(Kling4States.text)
            await query.message.answer(
                "Отправьте ID уже созданной задачи из кабинета KIE. Новая генерация не создаётся.",
                reply_markup=navigation(back_label="← Отмена"),
            )
        else:
            raise Kling4Error("Неизвестное действие.")
    except (
        Wan3PrimeValidationError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
    ) as exc:
        await query.message.answer(
            str(exc)
            if isinstance(exc, Wan3PrimeValidationError)
            else "Параметры изменились. Вернитесь в редактор и повторите действие.",
            reply_markup=navigation(),
        )
    await query.answer()


async def media_menu(message, recipe, path):
    value = get_path(recipe, path)
    values = value if isinstance(value, list) else ([value] if value else [])
    b = InlineKeyboardBuilder()
    for index, _ in enumerate(values):
        if index:
            b.button(text=f"↑ {index + 1}", callback_data=f"k4:up:{path}:{index}")
        b.button(text=f"Удалить {index + 1}", callback_data=f"k4:delete:{path}:{index}")
    b.adjust(2)
    label = {
        "image_urls": "Фото",
        "video_urls": "Видео",
        "video_url": "Видео персонажа",
        "voice_url": "Голос персонажа",
        "audio_url": "Голос",
        "first_frame_url": "Первый кадр",
        "keyframe_urls": "Промежуточные кадры",
        "last_frame_url": "Последний кадр",
    }[path.split(".")[-1]]
    await message.answer(
        f"{label} · загружено: {len(values)}\n"
        "Отправьте файл или публичную ссылку. Фото лучше отправлять документом, чтобы сохранить оригинал.\n"
        "Для нескольких файлов порядок показан номерами."
        + (
            " Видео персонажа должно быть одним непрерывным планом."
            if path.endswith(".video_url")
            else ""
        ),
        reply_markup=navigation(b, back=field_parent(path), back_label="← Готово"),
    )


@router.message(StateFilter(Kling4States.text))
@serialized_text
async def text(message: types.Message, state: FSMContext):
    if not await admin(message):
        return
    if not message.text:
        return
    current = await state.get_data()
    recipe = current.get("k4_recipe", fresh())
    field = current.get("k4_field")
    try:
        if field == "adopt":
            await kling4_lifecycle.adopt(
                await actor(message.from_user.id),
                current["k4_adopt"],
                message.text.strip(),
            )
        else:
            value = message.text
            if field == "duration":
                value = int(value)
                if not 3 <= value <= 30:
                    raise Kling4Error("Допустимо 3–30 секунд.")
            elif field.endswith(".description") and len(value) > 100:
                raise Kling4Error("Описание: до 100 символов.")
            set_path(
                recipe,
                field,
                None if value == "-" and field.endswith(".description") else value,
            )
            await save(state, recipe)
        await show(message, state)
    except (Wan3PrimeValidationError, ValueError) as exc:
        await message.answer(str(exc), reply_markup=navigation(back_label="← Отмена"))


@router.message(StateFilter(Kling4States.editing))
async def automatic(message: types.Message, state: FSMContext):
    await automatic_composer.handle(message, state)


@router.message(StateFilter(Kling4States.media))
async def media(message: types.Message, state: FSMContext):
    if not await admin(message):
        return
    current = await state.get_data()
    recipe = current.get("k4_recipe", fresh())
    path = current.get("k4_field", "")
    if await state.get_state() != Kling4States.media.state or not isinstance(path, str):
        return
    kind = (
        "audio"
        if path.endswith(("voice_url", "audio_url"))
        else "video"
        if path.endswith(("video_url", "video_urls"))
        else "image"
    )
    try:
        value = get_path(recipe, path)
        maximum = (
            10
            if path == "image_urls"
            else 5
            if path == "video_urls"
            else 8
            if path == "keyframe_urls"
            else 4
            if path.endswith("image_urls")
            else 1
        )
        if isinstance(value, list) and len(value) >= maximum:
            raise Kling4Error("Лимит поля достигнут. Удалите лишний материал.")
        if message.text:
            from bot.services.wan3_prime_storage import wan3_prime_storage

            result = await wan3_prime_storage.import_url(
                await actor(message.from_user.id), kind=kind, url=message.text.strip()
            )
        else:
            file = (
                message.document
                or message.video
                or message.audio
                or message.voice
                or (message.photo[-1] if message.photo else None)
            )
            if not file:
                raise Kling4Error("Отправьте файл или публичную ссылку.")
            from bot.wan3_prime_api import store_telegram_wan3_prime_media

            name = getattr(file, "file_name", None) or (
                "voice.ogg"
                if message.voice
                else "image.jpg"
                if message.photo
                else "video.mp4"
            )
            if message.voice or name.lower().endswith((".ogg", ".oga", ".m4a")):
                await message.answer(
                    "Голос будет преобразован в MP3 для KIE. Исходное сообщение останется в Telegram."
                )
            result = await store_telegram_wan3_prime_media(
                telegram_id=message.from_user.id,
                bot=message.bot,
                file_id=file.file_id,
                filename=name,
                kind=kind,
                declared_size=file.file_size,
            )
        # Serialize only the state mutation, not Telegram/download network I/O.
        # A newly selected field/session cancels stale uploads, even if its path matches.
        async with actor_lock(message, state):
            latest = await state.get_data()
            if (
                latest.get("k4_field") != path
                or latest.get("k4_media_session") != current.get("k4_media_session")
                or await state.get_state() != Kling4States.media.state
            ):
                return
            recipe = latest.get("k4_recipe", recipe)
            value = get_path(recipe, path)
            if isinstance(value, list) and len(value) >= maximum:
                raise Kling4Error("Лимит поля достигнут. Удалите лишний материал.")
            set_path(
                recipe,
                path,
                [*(value or []), result["url"]]
                if path.endswith("_urls")
                else result["url"],
            )
            await save(state, recipe)
            await media_menu(message, recipe, path)

    except (Wan3PrimeValidationError, ValueError, KeyError, TypeError) as exc:
        await message.answer(
            str(exc)
            if isinstance(exc, Wan3PrimeValidationError)
            else "Не удалось добавить материал. Вернитесь в редактор и повторите загрузку.",
            reply_markup=navigation(),
        )
