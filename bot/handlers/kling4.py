"""Telegram editor for the same typed Kling4 recipes as Mini App."""

from __future__ import annotations

import asyncio
import html
import logging
import re
import uuid
import weakref
from functools import wraps

from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.kling4_editor_view import (
    keyboard_rows,
    public_error,
    render_editor_card,
    task_status_label,
)
from bot.services.kling4_contract import RATIOS, Kling4Error
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
            if not await access_allowed(message):
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


async def access_allowed(event):
    from bot.kling4_tariff import kling4_public_enabled

    if config.is_admin(event.from_user.id) or kling4_public_enabled():
        return True
    if isinstance(event, types.CallbackQuery):
        await event.answer("Kling 4 пока недоступен.", show_alert=True)
    else:
        await event.answer("Kling 4 пока недоступен.")
    return False


async def actor(telegram_id):
    from bot.wan3_prime_api import _telegram_actor

    return await _telegram_actor(telegram_id)


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


async def materials_menu(message, recipe):
    data = recipe["input"]
    b = InlineKeyboardBuilder()
    b.button(text="+ Персонаж / объект по фото", callback_data="k4:new:image")
    b.button(text="+ Персонаж по видео", callback_data="k4:new:video")
    b.button(text="+ Голос", callback_data="k4:new:voice")
    for i, item in enumerate(data.get("elements") or []):
        b.button(text=f"Персонаж @{item['name']}", callback_data=f"k4:element:{i}")
    for i, item in enumerate(data.get("voices") or []):
        b.button(text=f"Голос @{item['name']}", callback_data=f"k4:voice:{i}")
    b.adjust(1)
    await message.answer(
        "Персонажи и голоса\nФотоэлемент: 2–4 ракурса одного персонажа или объекта. "
        "Видеоэлемент: один непрерывный план 3–8с. Используйте @имя в промпте.",
        reply_markup=navigation(b),
    )


async def material_menu(message, recipe, kind, index):
    items = recipe["input"].get("elements" if kind == "element" else "voices") or []
    if not 0 <= index < len(items):
        raise Kling4Error("Материал больше не существует.")
    item = items[index]
    prefix = ("elements" if kind == "element" else "voices") + f".{index}."
    b = InlineKeyboardBuilder()
    b.button(text="Имя: @" + item["name"], callback_data="k4:text:" + prefix + "name")
    for field, label in (
        ("image_urls", "Фото"),
        ("video_url", "Видео"),
        ("audio_url", "Аудио"),
    ):
        if field in item:
            count = (
                len(item[field]) if isinstance(item[field], list) else bool(item[field])
            )
            b.button(
                text=f"{label} ({int(count)})",
                callback_data="k4:media:" + prefix + field,
            )
    if kind == "element":
        b.button(text="Описание", callback_data="k4:text:" + prefix + "description")
        if item.get("tag") in (None, "character"):
            b.button(
                text="Привязанный голос",
                callback_data="k4:media:" + prefix + "voice_url",
            )
        if "image_urls" in item:
            b.button(
                text="Тип: " + item.get("tag", "Авто"), callback_data=f"k4:tag:{index}"
            )
    b.button(text="Удалить", callback_data=f"k4:remove:{kind}:{index}")
    b.adjust(2)
    guidance = (
        "\nНажмите «Фото» и загрузите 2–4 фото. Первое — основной ракурс, остальные — дополнительные."
        if "image_urls" in item
        else "\nОдно видео 3–8с, без склеек, короткая сторона от 700px."
        if "video_url" in item
        else "\nMP3/WAV с речью, до 30с."
    )
    await message.answer(
        "Материал @" + html.escape(item["name"]) + guidance,
        reply_markup=navigation(
            b, back="k4:materials", back_label="← Персонажи и голоса"
        ),
    )


def keyboard(recipe):
    b = InlineKeyboardBuilder()
    for row in keyboard_rows(recipe, RATIOS):
        b.row(
            *[
                types.InlineKeyboardButton(text=text, callback_data=callback)
                for text, callback in row
            ]
        )
    return b.as_markup()


async def show(message, state, *, edit=False):
    from bot.kling4_tariff import format_editor_price

    data = await state.get_data()
    recipe = data.get("k4_recipe", fresh())
    await state.set_state(Kling4States.editing)
    await state.update_data(k4_field=None, k4_media_session=None, k4_text_session=None)
    send = message.edit_text if edit else message.answer
    try:
        await send(
            render_editor_card(
                recipe,
                format_editor_price(
                    recipe, is_admin=config.is_admin(state.key.user_id)
                ),
            ),
            parse_mode="HTML",
            reply_markup=keyboard(recipe),
        )
    except TelegramBadRequest as exc:
        # Boundary clicks and the current-duration button can leave the card
        # unchanged. Telegram rejects that edit; it must not create a duplicate.
        if not edit or "message is not modified" not in exc.message.lower():
            raise


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


async def launch_confirmed(message, state, recipe, identity, quote, key, session):
    """Launch one frozen quote after the actor's required confirmation."""
    result = await kling4_lifecycle.launch(
        identity, recipe, quote["quote_hash"], key
    )
    latest = await state.get_data()
    active = latest.get("k4_session") == session and await state.get_state() in {
        Kling4States.editing.state,
        Kling4States.text.state,
    }
    if active:
        await state.update_data(
            k4_last_task=result["task_id"],
            k4_key=None,
            _prompt_fragment_submit_token=None,
        )
        await state.set_state(Kling4States.editing)
    logger.info(
        "Kling4 Telegram prompt submitted: telegram_id=%s task_id=%s request_id=%s status=%s",
        identity.telegram_id,
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
        heading
        + "\n"
        + f"Задача: {result['task_id']}\n"
        + (
            "Проверьте промпт и референсы перед следующим запуском."
            if status == "failed"
            else "Результат придёт в Telegram. Можно отправить следующий промпт."
        ),
        reply_markup=keyboard(recipe) if active else None,
    )
    return result


async def launch_prompt(message, state, recipe):
    """Resolve the measured quote, then require confirmation for paid actors."""
    from bot.kling4_tariff import format_price

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
        return None
    await state.update_data(k4_quote=quote, k4_key=key)
    if not identity.is_admin:
        confirm = InlineKeyboardBuilder()
        confirm.row(
            types.InlineKeyboardButton(
                text="Подтвердить и создать", callback_data="k4:confirm"
            )
        )
        await message.answer(
            format_price(quote) + "\n\nПодтвердите платный запуск.",
            reply_markup=navigation(confirm, back="k4:done", back_label="Отмена"),
        )
        return None
    await message.answer(format_price(quote))
    return await launch_confirmed(
        message,
        state,
        recipe,
        identity,
        quote,
        key,
        current.get("k4_session"),
    )


@router.message(Command("kling4"))
@serialized
async def command(message: types.Message, state: FSMContext):
    if not await access_allowed(message):
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
    if not await access_allowed(query):
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
            other = (
                parts[2]
                if len(parts) > 2
                else "keyframe"
                if recipe["mode"] == "reference"
                else "reference"
            )
            if other not in {"reference", "keyframe"}:
                raise Kling4Error("Неверный режим Kling 4.")
            if other == recipe["mode"]:
                await show(query.message, state)
                await query.answer()
                return
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
            await show(query.message, state, edit=True)
        elif action in {"resolution", "ratio", "sound"}:
            if action == "resolution":
                selected = (
                    parts[2]
                    if len(parts) > 2
                    else "1080p"
                    if inp["resolution"] == "720p"
                    else "720p"
                )
                if selected not in {"720p", "1080p"}:
                    raise Kling4Error("Разрешение: 720p или 1080p.")
                inp["resolution"] = selected
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
            else:
                await query.answer(
                    "Без видеореференса Kling 4 создаёт звук автоматически.",
                    show_alert=True,
                )
                return
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
            names = {
                entry["name"].casefold()
                for group in ("elements", "voices")
                for entry in inp.get(group) or []
            }
            stem = "Voice" if kind == "voice" else "Hero"
            number = 1
            while f"{stem}{number}".casefold() in names:
                number += 1
            name = f"{stem}{number}"
            if kind == "voice":
                item = {"name": name, "audio_url": ""}
            else:
                item = {
                    "name": name,
                    **(
                        {"image_urls": []}
                        if kind == "image"
                        else {"video_url": "", "tag": "character"}
                    ),
                }
            items.append(item)
            await save(state, recipe)
            await state.set_state(Kling4States.editing)
            await material_menu(
                query.message,
                recipe,
                "voice" if kind == "voice" else "element",
                len(items) - 1,
            )
        elif action in {"element", "voice"}:
            await state.set_state(Kling4States.editing)
            await material_menu(query.message, recipe, action, int(parts[2]))
        elif action == "tag":
            item = inp["elements"][int(parts[2])]
            tags = (
                None,
                "character",
                "animal",
                "prop",
                "costume",
                "scene",
                "effect",
                "others",
            )
            tag = tags[(tags.index(item.get("tag")) + 1) % len(tags)]
            if tag is None:
                item.pop("tag", None)
            else:
                item["tag"] = tag
            if tag not in {None, "character"}:
                item.pop("voice_url", None)
            await save(state, recipe)
            await state.set_state(Kling4States.editing)
            await material_menu(query.message, recipe, "element", int(parts[2]))
        elif action == "remove":
            inp["elements" if parts[2] == "element" else "voices"].pop(int(parts[3]))
            await save(state, recipe)
            await state.set_state(Kling4States.editing)
            await materials_menu(query.message, recipe)
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
            await state.update_data(
                k4_field=path,
                k4_media_session=uuid.uuid4().hex,
                k4_media_uploads=[],
                k4_media_receipts={},
            )
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
            # A manual reorder becomes the fixed prefix for subsequent uploads.
            await state.update_data(k4_media_uploads=[])
            await save(state, recipe)
            await media_menu(query.message, recipe, path)
        elif action == "confirm":
            quote = current.get("k4_quote")
            key = current.get("k4_key")
            if not isinstance(quote, dict) or not isinstance(key, str):
                raise Kling4Error(
                    "Расчёт устарел. Отправьте промпт заново.", status=409
                )
            await launch_confirmed(
                query.message,
                state,
                recipe,
                await actor(query.from_user.id),
                quote,
                key,
                current.get("k4_session"),
            )
        elif action in {"quote", "launch"}:
            # Old message keyboards cannot bypass automatic reference readiness.
            await show(query.message, state)
        elif action == "history":
            history = await kling4_lifecycle.history(await actor(query.from_user.id))
            b = InlineKeyboardBuilder()
            for task in history[:10]:
                b.button(
                    text=f"{task['task_id']} · {task_status_label(task['status'])}",
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
            b.adjust(1)
            b.row(
                types.InlineKeyboardButton(text="← История", callback_data="k4:history")
            )
            await state.set_state(Kling4States.editing)
            await query.message.answer(
                f"Задача: {task['task_id']}\n{task_status_label(task['status'])}",
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
            await query.message.answer(
                "Проверяем запуск видео. Не запускайте его повторно. Если ожидание затянулось, обратитесь в поддержку.",
                reply_markup=navigation(),
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
            public_error(exc)
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
            else " Для элемента нужно 2–4 фото; первое — основной ракурс."
            if path.startswith("elements.") and path.endswith(".image_urls")
            else ""
        ),
        reply_markup=navigation(b, back=field_parent(path), back_label="← Готово"),
    )


@router.message(StateFilter(Kling4States.text))
@serialized_text
async def text(message: types.Message, state: FSMContext):
    if not await access_allowed(message):
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
        if field.startswith(("elements.", "voices.")):
            await state.set_state(Kling4States.editing)
            await material_menu(
                message,
                recipe,
                "element" if field.startswith("elements.") else "voice",
                int(field.split(".")[1]),
            )
        else:
            await show(message, state)
    except (Wan3PrimeValidationError, ValueError) as exc:
        await message.answer(public_error(exc), reply_markup=navigation(back_label="← Отмена"))


@router.message(StateFilter(Kling4States.editing))
async def automatic(message: types.Message, state: FSMContext):
    await automatic_composer.handle(message, state)


@router.message(StateFilter(Kling4States.media))
async def media(message: types.Message, state: FSMContext):
    if not await access_allowed(message):
        return
    current = await state.get_data()
    recipe = current.get("k4_recipe", fresh())
    path = current.get("k4_field", "")
    if await state.get_state() != Kling4States.media.state or not isinstance(path, str):
        return
    text_value = str(getattr(message, "text", "") or "").strip()
    if text_value.startswith("/"):
        raise SkipHandler
    if text_value and not re.fullmatch(r"https?://\S+", text_value, re.IGNORECASE):
        await automatic_composer.queue(message, state, current.get("k4_session"))
        return
    mid = getattr(message, "message_id", None)
    session = current.get("k4_session")
    key = automatic_composer.key(state, session)
    pending_id = str(mid) if isinstance(mid, int) else uuid.uuid4().hex
    if isinstance(mid, int) and (
        str(mid) in current.get("k4_media_receipts", {})
        or pending_id in automatic_composer.pending.get(key, {})
    ):
        return
    kind = (
        "audio"
        if path.endswith(("voice_url", "audio_url"))
        else "video"
        if path.endswith(("video_url", "video_urls"))
        else "image"
    )
    try:
        file = (
            message.document
            or message.video
            or message.audio
            or message.voice
            or (message.photo[-1] if message.photo else None)
        )
        receipt = str(
            getattr(file, "file_unique_id", None)
            or getattr(file, "file_id", None)
            or text_value
        )
        async with actor_lock(message, state):
            latest = await state.get_data()
            if (
                latest.get("k4_field") != path
                or latest.get("k4_media_session") != current.get("k4_media_session")
                or await state.get_state() != Kling4States.media.state
            ):
                return
            receipts = latest.get("k4_media_receipts", {})
            if isinstance(mid, int) and (
                str(mid) in receipts
                or pending_id in automatic_composer.pending.get(key, {})
            ):
                return
            future = asyncio.get_running_loop().create_future()
            automatic_composer.pending.setdefault(key, {})[pending_id] = future
            errors = latest.get("k4_upload_errors", {})
            errors[receipt] = pending_id
            await state.update_data(
                k4_upload_errors=errors,
                k4_media_version=latest.get("k4_media_version", 0) + 1,
                k4_album_pending=bool(getattr(message, "media_group_id", None))
                or latest.get("k4_album_pending", False),
            )
        caption = str(getattr(message, "caption", "") or "").strip()
        if caption:
            await automatic_composer.queue(
                message.model_copy(update={"text": caption, "entities": []}),
                state,
                session,
            )
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
        if text_value:
            from bot.services.wan3_prime_storage import wan3_prime_storage

            result = await wan3_prime_storage.import_url(
                await actor(message.from_user.id), kind=kind, url=text_value
            )
        else:
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
                    "Подготавливаю голос. Исходное сообщение останется в Telegram."
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
                errors = latest.get("k4_upload_errors", {})
                if errors.get(receipt) == pending_id:
                    errors.pop(receipt, None)
                    await state.update_data(k4_upload_errors=errors)
                return
            recipe = latest.get("k4_recipe", recipe)
            value = get_path(recipe, path)
            receipts = latest.get("k4_media_receipts", {})
            if isinstance(mid, int) and str(mid) in receipts:
                return
            if isinstance(value, list) and len(value) >= maximum:
                raise Kling4Error("Лимит поля достигнут. Удалите лишний материал.")
            if path.endswith("_urls") and isinstance(mid, int):
                value = value or []
                previous = latest.get("k4_media_uploads", [])
                known = {entry["url"] for entry in previous}
                prefix = [url for url in value if url not in known]
                ordered = sorted(
                    [entry for entry in previous if entry["url"] in value]
                    + [{"url": result["url"], "message_id": mid}],
                    key=lambda entry: entry["message_id"],
                )
                urls = prefix + [entry["url"] for entry in ordered]
                await state.update_data(k4_media_uploads=ordered)
            else:
                urls = (
                    [*(value or []), result["url"]] if path.endswith("_urls") else None
                )
            set_path(
                recipe,
                path,
                urls if path.endswith("_urls") else result["url"],
            )
            if isinstance(mid, int):
                receipts[str(mid)] = True
            errors = latest.get("k4_upload_errors", {})
            errors.pop(receipt, None)
            await state.update_data(
                k4_media_receipts=receipts,
                k4_upload_errors=errors,
            )
            await save(state, recipe)
            await media_menu(message, recipe, path)

    except Exception as exc:  # noqa: BLE001 - failed uploads must release queued prompts
        if "receipt" in locals():
            latest = await state.get_data()
            errors = latest.get("k4_upload_errors", {})
            errors[receipt] = True
            await state.update_data(k4_upload_errors=errors)
        await message.answer(
            public_error(exc)
            if isinstance(exc, Wan3PrimeValidationError)
            else "Не удалось добавить материал. Вернитесь в редактор и повторите загрузку.",
            reply_markup=navigation(),
        )
        logger.warning(
            "Kling4 targeted media failed: telegram_id=%s session=%s field=%s error_type=%s",
            message.from_user.id,
            session,
            path,
            type(exc).__name__,
        )
    finally:
        if "future" in locals() and not future.done():
            future.set_result(None)
        group = automatic_composer.pending.get(key, {})
        group.pop(pending_id, None)
        if not group:
            automatic_composer.pending.pop(key, None)
