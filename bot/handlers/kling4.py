"""Telegram editor for the same typed admin-only Kling4 recipes as Mini App."""

from __future__ import annotations

import html
import uuid

from aiogram import F, Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.services.kling4_contract import RATIOS, Kling4Error, require_admin
from bot.services.kling4_lifecycle import kling4_lifecycle
from bot.services.wan3_prime_media import Wan3PrimeValidationError

router = Router(name="kling4")


class Kling4States(StatesGroup):
    editing = State()
    text = State()
    media = State()


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


def keyboard(recipe):
    b = InlineKeyboardBuilder()
    data = recipe["input"]
    b.button(text="✏️ Промпт", callback_data="k4:text:prompt")
    b.button(text=f"⏱ {data['duration']}с", callback_data="k4:text:duration")
    b.button(text=data["resolution"], callback_data="k4:resolution")
    b.button(text=data.get("aspect_ratio", "auto"), callback_data="k4:ratio")
    b.button(text="Режим: " + recipe["mode"], callback_data="k4:mode")
    if recipe["mode"] == "reference":
        b.button(
            text=f"Фото ({len(data.get('image_urls', []))}/10)",
            callback_data="k4:media:image_urls",
        )
        b.button(
            text=f"Видео ({len(data.get('video_urls', []))}/5)",
            callback_data="k4:media:video_urls",
        )
        if data.get("video_urls"):
            b.button(
                text="Исходный звук: "
                + ("да" if data.get("keep_original_sound") else "нет"),
                callback_data="k4:sound",
            )
        b.button(text="+ Элемент по фото", callback_data="k4:new:image")
        b.button(text="+ Персонаж по видео", callback_data="k4:new:video")
        b.button(text="+ Голос", callback_data="k4:new:voice")
        for i, e in enumerate(data.get("elements", [])):
            b.button(text=f"Элемент @{e['name']}", callback_data=f"k4:element:{i}")
        for i, v in enumerate(data.get("voices", [])):
            b.button(text=f"Голос @{v['name']}", callback_data=f"k4:voice:{i}")
    else:
        for path, label in [
            ("first_frame_url", "Первый кадр"),
            ("keyframe_urls", "Промежуточные кадры"),
            ("last_frame_url", "Последний кадр"),
        ]:
            b.button(text=label, callback_data="k4:media:" + path)
    b.button(text="💰 Рассчитать", callback_data="k4:quote")
    b.button(text="📋 История", callback_data="k4:history")
    b.adjust(2)
    return b.as_markup()


async def show(message, state):
    data = await state.get_data()
    recipe = data.get("k4_recipe", fresh())
    inp = recipe["input"]
    await state.set_state(Kling4States.editing)
    await message.answer(
        "<b>Kling 4 · администратор</b>\n"
        + f"{recipe['mode']} · {inp['duration']}с · {inp['resolution']}\n"
        + html.escape(inp["prompt"] or "Добавьте промпт.")
        + "\n\nБананы не списываются. Расход KIE рассчитывается перед подтверждением.",
        parse_mode="HTML",
        reply_markup=keyboard(recipe),
    )


async def save(state, recipe):
    await state.update_data(k4_recipe=recipe, k4_quote=None, k4_key=uuid.uuid4().hex)


@router.message(Command("kling4"))
async def command(message: types.Message, state: FSMContext):
    if not await admin(message):
        return
    await state.clear()
    await save(state, fresh())
    await show(message, state)


@router.callback_query(F.data.startswith("k4:"))
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
            await save(state, fresh())
            await show(query.message, state)
        elif action == "done":
            await show(query.message, state)
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
        elif action in {"resolution", "ratio", "sound"}:
            if action == "resolution":
                inp["resolution"] = "1080p" if inp["resolution"] == "720p" else "720p"
            elif action == "ratio":
                inp["aspect_ratio"] = RATIOS[
                    (RATIOS.index(inp.get("aspect_ratio", "auto")) + 1) % len(RATIOS)
                ]
            elif recipe["mode"] == "reference" and inp.get("video_urls"):
                inp["keep_original_sound"] = not inp.get("keep_original_sound", False)
            await save(state, recipe)
            await show(query.message, state)
        elif action == "text":
            field = parts[2]
            if field not in {"prompt", "duration"} and not field.startswith(
                ("elements.", "voices.")
            ):
                raise Kling4Error("Неверное поле.")
            await state.update_data(k4_field=field)
            await state.set_state(Kling4States.text)
            await query.message.answer(
                "Отправьте "
                + (
                    "целое число секунд от 3 до 30."
                    if field == "duration"
                    else "новое значение. Для удаления необязательного поля отправьте «-»."
                )
            )
        elif action == "new":
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
            await show(query.message, state)
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
            b.button(text="Назад", callback_data="k4:done")
            b.adjust(2)
            await query.message.answer(
                "Материал @" + item["name"], reply_markup=b.as_markup()
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
            await state.update_data(k4_field=path)
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
        elif action == "quote":
            quote = await kling4_lifecycle.quote(
                await actor(query.from_user.id), recipe
            )
            await state.update_data(k4_quote=quote)
            b = InlineKeyboardBuilder()
            b.button(text="Подтвердить и создать", callback_data="k4:launch")
            b.button(text="Вернуться", callback_data="k4:done")
            await query.message.answer(
                f"Расход KIE: {quote['provider_credits']} credits. Бананы: 0.\nОплачиваемых секунд: {quote['billed_seconds']}.",
                reply_markup=b.as_markup(),
            )
        elif action == "launch":
            quote = current.get("k4_quote") or {}
            result = await kling4_lifecycle.launch(
                await actor(query.from_user.id),
                recipe,
                quote.get("quote_hash"),
                current.get("k4_key", ""),
            )
            await state.update_data(k4_last_task=result["task_id"])
            await query.message.answer(
                f"Kling 4: {result['status']}\n{result['task_id']}\nРезультат появится в истории и придёт в Telegram."
            )
        elif action == "history":
            history = await kling4_lifecycle.history(await actor(query.from_user.id))
            b = InlineKeyboardBuilder()
            for task in history[:10]:
                b.button(
                    text=task["status"] + " · " + task["task_id"][-12:],
                    callback_data="k4:task:" + task["task_id"],
                )
            b.button(text="Редактор", callback_data="k4:done")
            b.adjust(1)
            await query.message.answer("История Kling 4", reply_markup=b.as_markup())
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
            await query.message.answer(
                f"{task['task_id']}\n{task['status']}\nРасход KIE: {task['actual_credits'] or 'уточняется'}",
                reply_markup=b.as_markup(),
            )
        elif action == "repeat":
            repeat = await kling4_lifecycle.owner_recipe(
                await actor(query.from_user.id), parts[2]
            )
            await save(state, repeat)
            await show(query.message, state)
        elif action == "adopt":
            await kling4_lifecycle.status(await actor(query.from_user.id), parts[2])
            await state.update_data(k4_adopt=parts[2], k4_field="adopt")
            await state.set_state(Kling4States.text)
            await query.message.answer(
                "Отправьте ID уже созданной задачи из кабинета KIE. Новая генерация не создаётся."
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
            else "Параметры изменились. Откройте /kling4 заново."
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
    b.button(text="Готово", callback_data="k4:done")
    b.adjust(2)
    await message.answer(
        "Отправьте материал файлом или публичную ссылку. Фото лучше отправлять документом, чтобы сохранить оригинал.\n"
        + f"Поле: {path}. Загружено: {len(values)}. Порядок показан номерами. Видео персонажа должно быть одним непрерывным планом.",
        reply_markup=b.as_markup(),
    )


@router.message(StateFilter(Kling4States.text))
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
            elif field == "prompt" and len(value) > 8000:
                raise Kling4Error("Промпт: до 8000 символов.")
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
        await message.answer(str(exc))


@router.message(StateFilter(Kling4States.media))
async def media(message: types.Message, state: FSMContext):
    if not await admin(message):
        return
    current = await state.get_data()
    recipe = current.get("k4_recipe", fresh())
    path = current.get("k4_field", "")
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
        # Reload after I/O so earlier slots are preserved.
        latest = await state.get_data()
        if (
            latest.get("k4_field") != path
            or await state.get_state() != Kling4States.media.state
        ):
            return
        recipe = latest.get("k4_recipe", recipe)
        value = get_path(recipe, path)
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
            else "Не удалось добавить материал. Откройте редактор заново."
        )
