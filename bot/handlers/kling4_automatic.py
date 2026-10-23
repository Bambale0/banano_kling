"""Automatic Telegram intake; the existing Kling4 lifecycle owns submission."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
import weakref
from copy import deepcopy
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from aiogram.dispatcher.event.bases import SkipHandler

from bot.services.kling4_contract import Kling4Error
from bot.services.prompt_fragment_coalescer import (
    PROMPT_FRAGMENT_LONG_QUIET_SECONDS,
    PROMPT_TEXT_STATES,
    PromptFragmentCoalescingMiddleware,
)
from bot.services.wan3_prime_media import Wan3PrimeValidationError

logger = logging.getLogger(__name__)


def detected_media(message):
    """Classify transport metadata; owned storage still checks actual bytes."""
    for field, kind in (
        ("photo", "image"),
        ("video", "video"),
        ("animation", "video"),
        ("audio", "audio"),
        ("voice", "audio"),
    ):
        file = getattr(message, field, None)
        if file:
            return kind, file[-1] if field == "photo" else file
    file = getattr(message, "document", None)
    url = str(getattr(message, "text", "") or "").strip()
    if not file and not re.fullmatch(r"https?://\S+", url, re.IGNORECASE):
        return None
    try:
        name = getattr(file, "file_name", "") if file else urlsplit(url).path
    except ValueError as exc:
        raise Kling4Error("Некорректная ссылка на референс.") from exc
    mime = str(getattr(file, "mime_type", "") or "").split("/", 1)[0]
    extension = PurePosixPath(name or "").suffix.lower()
    for kind, extensions in (
        ("image", {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}),
        ("video", {".mp4", ".mov"}),
        ("audio", {".mp3", ".wav", ".ogg", ".oga", ".m4a"}),
    ):
        if mime == kind or extension in extensions:
            return kind, file
    if file or re.fullmatch(r"https?://\S+", url, re.IGNORECASE):
        raise Kling4Error(
            "Отправьте фото, видео или аудиофайл. Для ссылки нужен адрес самого файла."
        )
    return None


def frame_recipe(recipe):
    """Explicit provider frame tags express intent without a mode picker."""
    data = recipe["input"]
    if recipe["mode"] != "reference" or not re.search(
        r"@(first_frame|last_frame|keyframe_\d+)\b", data["prompt"]
    ):
        return recipe
    if data.get("video_urls") or data.get("voices") or data.get("elements"):
        raise Kling4Error(
            "Для кадрового видео используйте только фото; видео и голоса — референсы."
        )
    photos = list(data.get("image_urls", []))
    if not photos:
        raise Kling4Error("Добавьте фото для указанных в промпте кадров.")
    result = {
        k: data[k]
        for k in ("prompt", "duration", "resolution", "aspect_ratio")
        if k in data
    }
    result["first_frame_url"] = photos.pop(0)
    if "@last_frame" in data["prompt"]:
        if not photos:
            raise Kling4Error("Для последнего кадра добавьте второе фото.")
        result["last_frame_url"] = photos.pop()
    if photos:
        result["keyframe_urls"] = photos
    return {"mode": "keyframe", "input": result}


class AutomaticComposer:
    def __init__(self):
        self.pending = {}
        self.coalescers = weakref.WeakValueDictionary()

    @staticmethod
    def key(state, session):
        return (state.key.bot_id, state.key.chat_id, state.key.user_id, session)

    async def queue(self, message, state, session):
        from . import kling4 as editor

        async with editor.actor_lock(message, state):
            current = await state.get_data()
            if current.get("k4_session") != session:
                return
            mid = getattr(message, "message_id", None)
            if isinstance(mid, int):
                receipts = current.get("k4_prompt_messages", {})
                if str(mid) in receipts:
                    return
                receipts[str(mid)] = True
                await state.update_data(k4_prompt_messages=receipts)
        key = self.key(state, session)
        middleware = self.coalescers.get(key)
        if middleware is None:
            middleware = PromptFragmentCoalescingMiddleware(order_by_message_id=True)
            self.coalescers[key] = middleware
        PROMPT_TEXT_STATES.add(editor.Kling4States.editing.state)

        async def submit(event, _data):
            await self.submit(event, state, session)

        await middleware(submit, message, {"state": state})

    async def submit(self, message, state, session):
        from . import kling4 as editor

        key = self.key(state, session)
        while True:
            pending = list(self.pending.get(key, {}).values())
            if pending:
                await asyncio.gather(*(asyncio.shield(future) for future in pending))
            snapshot = await state.get_data()
            version = snapshot.get("k4_media_version")
            if snapshot.get("k4_album_pending"):
                # Telegram provides no final-album marker. Reuse the existing
                # managed long-fragment quiet window after the latest activity.
                await asyncio.sleep(PROMPT_FRAGMENT_LONG_QUIET_SECONDS)
            async with editor.actor_lock(message, state):
                current = await state.get_data()
                if (
                    current.get("k4_session") != session
                    or await state.get_state() != editor.Kling4States.editing.state
                ):
                    return
                if self.pending.get(key) or current.get("k4_media_version") != version:
                    continue
                if current.get("k4_upload_errors"):
                    await message.answer(
                        "Референс не загрузился. Отправьте его ещё раз или очистите медиа, затем повторите промпт."
                    )
                    return
                recipe = deepcopy(current.get("k4_recipe", editor.fresh()))
                recipe["input"]["prompt"] = message.text.strip()
                try:
                    recipe = frame_recipe(recipe)
                    await editor.save(state, recipe)
                    await state.update_data(k4_album_pending=False)
                    await editor.launch_prompt(message, state, recipe)
                except Wan3PrimeValidationError as exc:
                    await message.answer(str(exc), reply_markup=editor.keyboard(recipe))
                return

    async def handle(self, message, state):
        from . import kling4 as editor

        if not await editor.admin(message):
            return
        if str(getattr(message, "text", "") or "").lstrip().startswith("/"):
            raise SkipHandler
        try:
            detected = detected_media(message)
        except Wan3PrimeValidationError as exc:
            async with editor.actor_lock(message, state):
                if await state.get_state() != editor.Kling4States.editing.state:
                    return
                current = await state.get_data()
                errors = current.get("k4_upload_errors", {})
                invalid = getattr(message, "document", None)
                receipt = str(
                    getattr(invalid, "file_unique_id", None)
                    or getattr(invalid, "file_id", None)
                    or getattr(message, "text", "")
                )
                errors[receipt] = True
                await state.update_data(k4_upload_errors=errors)
            await message.answer(str(exc))
            return
        file = detected[1] if detected else None
        receipt = str(
            getattr(file, "file_unique_id", None)
            or getattr(file, "file_id", None)
            or getattr(message, "text", "")
        )
        async with editor.actor_lock(message, state):
            if await state.get_state() != editor.Kling4States.editing.state:
                return
            current = await state.get_data()
            session = current.get("k4_session") or uuid.uuid4().hex
            await state.update_data(k4_session=session)
            if detected:
                key = self.key(state, session)
                mid = str(getattr(message, "message_id", uuid.uuid4().hex))
                receipts = current.get("k4_media_messages", {})
                if mid in receipts or mid in self.pending.get(key, {}):
                    return
                future = asyncio.get_running_loop().create_future()
                self.pending.setdefault(key, {})[mid] = future
                # Pending uploads survive process loss as a blocking marker.
                # A prompt cannot silently omit a reference after a restart.
                errors = current.get("k4_upload_errors", {})
                errors[receipt] = True
                await state.update_data(
                    k4_upload_errors=errors,
                    k4_media_version=current.get("k4_media_version", 0) + 1,
                    k4_album_pending=bool(getattr(message, "media_group_id", None))
                    or current.get("k4_album_pending", False),
                )
        if not detected:
            if str(getattr(message, "text", "") or "").strip():
                await self.queue(message, state, session)
            return

        kind, file = detected
        caption = str(getattr(message, "caption", "") or "").strip()
        try:
            if caption:
                await self.queue(
                    message.model_copy(update={"text": caption, "entities": []}),
                    state,
                    session,
                )
            if file:
                from bot.wan3_prime_api import store_telegram_wan3_prime_media

                result = await store_telegram_wan3_prime_media(
                    telegram_id=message.from_user.id,
                    bot=message.bot,
                    file_id=file.file_id,
                    filename=getattr(file, "file_name", None)
                    or (
                        "voice.ogg"
                        if getattr(message, "voice", None)
                        else "image.jpg"
                        if kind == "image"
                        else "video.mp4"
                        if kind == "video"
                        else "audio.mp3"
                    ),
                    kind=kind,
                    declared_size=getattr(file, "file_size", None),
                )
            else:
                from bot.services.wan3_prime_storage import wan3_prime_storage

                result = await wan3_prime_storage.import_url(
                    await editor.actor(message.from_user.id),
                    kind=kind,
                    url=message.text.strip(),
                )
            async with editor.actor_lock(message, state):
                latest = await state.get_data()
                if (
                    latest.get("k4_session") != session
                    or await state.get_state() != editor.Kling4States.editing.state
                ):
                    return
                recipe = deepcopy(latest.get("k4_recipe", editor.fresh()))
                drafts = deepcopy(latest.get("k4_drafts", {}))
                if recipe["mode"] == "keyframe":
                    drafts["keyframe"] = deepcopy(recipe)
                    # Restored references and ordered frames form a fixed
                    # prefix. Old automatic-upload receipts must not move
                    # those images behind the newly restored frame images.
                    latest["k4_auto_uploads"] = [
                        entry
                        for entry in latest.get("k4_auto_uploads", [])
                        if entry["kind"] != "image"
                    ]
                    reference = drafts.get("reference")
                    if reference:
                        # Resume the reference draft as well as keeping the
                        # frame images; automatic switching must not hide its
                        # existing elements, voices or ordinary references.
                        frame_data = recipe["input"]
                        recipe = deepcopy(reference)
                        recipe["input"].update(
                            {
                                k: frame_data[k]
                                for k in (
                                    "prompt",
                                    "duration",
                                    "resolution",
                                    "aspect_ratio",
                                )
                                if k in frame_data
                            }
                        )
                        images = recipe["input"].setdefault("image_urls", [])
                        for url in (
                            frame_data.get("first_frame_url"),
                            *(frame_data.get("keyframe_urls") or []),
                            frame_data.get("last_frame_url"),
                        ):
                            if url and url not in images:
                                images.append(url)
                self.attach(
                    recipe,
                    latest,
                    kind,
                    result["url"],
                    int(mid) if mid.isdigit() else 0,
                )
                receipts = latest.get("k4_media_messages", {})
                receipts[mid] = True
                errors = latest.get("k4_upload_errors", {})
                errors.pop(receipt, None)
                await editor.save(state, recipe)
                await state.update_data(
                    k4_drafts=drafts,
                    k4_auto_uploads=latest["k4_auto_uploads"],
                    k4_media_messages=receipts,
                    k4_upload_errors=errors,
                )
                logger.info(
                    "Kling4 Telegram reference stored: telegram_id=%s session=%s kind=%s message_id=%s",
                    message.from_user.id,
                    session,
                    kind,
                    mid,
                )
                if not caption:
                    await editor.show(message, state)
        except Exception as exc:  # noqa: BLE001 - failed owned uploads must block queued generation
            async with editor.actor_lock(message, state):
                latest = await state.get_data()
                if latest.get("k4_session") == session:
                    errors = latest.get("k4_upload_errors", {})
                    errors[receipt] = True
                    await state.update_data(k4_upload_errors=errors)
            await message.answer(
                str(exc)
                if isinstance(exc, Wan3PrimeValidationError)
                else "Не удалось загрузить референс. Отправьте файл ещё раз."
            )
            logger.warning(
                "Kling4 Telegram reference failed: telegram_id=%s session=%s kind=%s error_type=%s",
                message.from_user.id,
                session,
                kind,
                type(exc).__name__,
            )
        finally:
            if not future.done():
                future.set_result(None)
            group = self.pending.get(key, {})
            group.pop(mid, None)
            if not group:
                self.pending.pop(key, None)

    @staticmethod
    def attach(recipe, state_data, kind, url, mid):
        data = recipe["input"]
        if recipe["mode"] == "keyframe":
            # Return to the ordered intake representation when new files arrive.
            # frame_recipe resolves frame intent again on the next prompt.
            data = {
                k: data[k]
                for k in ("prompt", "duration", "resolution", "aspect_ratio")
                if k in data
            } | {
                "image_urls": [
                    v
                    for v in [
                        data.get("first_frame_url"),
                        *data.get("keyframe_urls", []),
                        data.get("last_frame_url"),
                    ]
                    if v
                ]
            }
            recipe.update(mode="reference", input=data)
        field = {"image": "image_urls", "video": "video_urls", "audio": "voices"}[kind]
        values = data.setdefault(field, [])
        if len(values) >= {"image": 10, "video": 5, "audio": 3}[kind]:
            raise Kling4Error(
                "Лимит референсов достигнут. Очистите медиа для новой задачи."
            )
        if (
            sum(
                len(data.get(k, []))
                for k in ("image_urls", "video_urls", "voices", "elements")
            )
            >= 15
        ):
            raise Kling4Error("Всего допустимо до 15 материалов.")
        previous = [
            e for e in state_data.get("k4_auto_uploads", []) if e["kind"] == kind
        ]
        known_urls = {e["url"] for e in previous}
        prefix = [
            v
            for v in values
            if (v["audio_url"] if kind == "audio" else v) not in known_urls
        ]
        actual_urls = {v["audio_url"] if kind == "audio" else v for v in values}
        ordered = sorted(
            [e for e in previous if e["url"] in actual_urls]
            + [{"kind": kind, "url": url, "message_id": mid}],
            key=lambda e: e["message_id"],
        )
        if kind == "audio":
            names = {v["name"] for v in [*prefix, *data.get("elements", [])]}
            voices = []
            for entry in ordered:
                index = 1
                while f"Voice{index}" in names:
                    index += 1
                name = f"Voice{index}"
                names.add(name)
                voices.append({"name": name, "audio_url": entry["url"]})
            data[field] = prefix + voices
        else:
            data[field] = prefix + [e["url"] for e in ordered]
        state_data["k4_auto_uploads"] = [
            e for e in state_data.get("k4_auto_uploads", []) if e["kind"] != kind
        ] + ordered
