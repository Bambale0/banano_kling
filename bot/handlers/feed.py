import io
import html
import hashlib
import logging
from urllib.parse import urlparse

import aiohttp
from PIL import Image, ImageOps
from aiogram import Router, F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, InputMediaPhoto

from bot.database import (
    get_feed_tasks,
    get_public_feed_task,
    increment_feed_share,
    like_feed_task,
    remove_task_from_feed,
    share_task_to_feed,
)
from bot.keyboards import (
    get_feed_card_keyboard,
    get_feed_empty_keyboard,
    get_reference_images_upload_keyboard,
)
from bot.states import GenerationStates

logger = logging.getLogger(__name__)
router = Router()
MAX_FEED_DOWNLOAD_BYTES = 80 * 1024 * 1024
MAX_TELEGRAM_PHOTO_BYTES = 9 * 1024 * 1024
MAX_PREVIEW_SIDE = 1600


def _feed_caption(task) -> str:
    seed = str(task.telegram_id or task.user_id or task.task_id or "anon")
    author_code = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]
    author = f"creator {author_code}"
    model = task.model or task.preset_id or "image"
    ratio = task.aspect_ratio or "auto"
    return (
        f"🔥 <b>Лента</b>\n\n"
        f"👤 <code>{author}</code>\n"
        f"🎨 <code>{model}</code>\n"
        f"📐 <code>{ratio}</code>\n\n"
        f"❤️ <code>{task.likes_count}</code>   "
        f"📤 <code>{task.shares_count}</code>\n"
        f"────────────"
    )


async def _show_empty(target) -> None:
    text = (
        "🔥 <b>Лента</b>\n\n"
        "Пока нет готовых публичных изображений. Самое время создать первый пост."
    )
    if isinstance(target, types.CallbackQuery):
        try:
            await target.message.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=get_feed_empty_keyboard(),
            )
        except TelegramBadRequest:
            try:
                await target.message.delete()
            except TelegramBadRequest:
                pass
            await target.message.answer(
                text,
                parse_mode="HTML",
                reply_markup=get_feed_empty_keyboard(),
            )
        await target.answer()
    else:
        await target.answer(
            text,
            parse_mode="HTML",
            reply_markup=get_feed_empty_keyboard(),
        )


def _filename_from_url(url: str) -> str:
    path = urlparse(url or "").path
    name = path.rsplit("/", 1)[-1] or "feed-preview.jpg"
    if "." not in name:
        name = f"{name}.jpg"
    return name[:80]


async def _download_preview(url: str) -> bytes | None:
    if not url:
        return None

    try:
        timeout = aiohttp.ClientTimeout(total=45)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; Telegram Bot Preview/1.0)",
                    "Accept": "image/*,*/*;q=0.8",
                },
            ) as response:
                if response.status != 200:
                    logger.warning("Feed preview download failed: status=%s url=%s", response.status, url)
                    return None

                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_FEED_DOWNLOAD_BYTES:
                    logger.warning("Feed preview is too large: bytes=%s url=%s", content_length, url)
                    return None

                chunks: list[bytes] = []
                total = 0
                async for chunk in response.content.iter_chunked(64 * 1024):
                    total += len(chunk)
                    if total > MAX_FEED_DOWNLOAD_BYTES:
                        logger.warning("Feed preview exceeded size limit: url=%s", url)
                        return None
                    chunks.append(chunk)
                return b"".join(chunks) if chunks else None
    except Exception as exc:
        logger.warning("Feed preview download error for %s: %s", url, exc)
        return None


def _prepare_preview_image(image_bytes: bytes) -> bytes:
    if len(image_bytes) <= MAX_TELEGRAM_PHOTO_BYTES:
        return image_bytes

    with Image.open(io.BytesIO(image_bytes)) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        image.thumbnail((MAX_PREVIEW_SIDE, MAX_PREVIEW_SIDE), Image.Resampling.LANCZOS)

        for quality in (90, 85, 80, 72):
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=quality, optimize=True)
            prepared = output.getvalue()
            if len(prepared) <= MAX_TELEGRAM_PHOTO_BYTES:
                return prepared

        output = io.BytesIO()
        image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        image.save(output, format="JPEG", quality=70, optimize=True)
        return output.getvalue()


async def _send_feed_photo(target, task, markup) -> bool:
    caption = _feed_caption(task)
    if not isinstance(target, types.CallbackQuery):
        try:
            await target.answer_photo(
                photo=task.result_url,
                caption=caption,
                parse_mode="HTML",
                reply_markup=markup,
            )
            return True
        except TelegramBadRequest as exc:
            logger.warning(
                "Cannot send feed task %s by URL (%s); trying file upload",
                task.task_id,
                exc,
            )

        image_bytes = await _download_preview(task.result_url)
        if not image_bytes:
            return False

        try:
            image_bytes = _prepare_preview_image(image_bytes)
            await target.answer_photo(
                photo=BufferedInputFile(
                    image_bytes, filename=_filename_from_url(task.result_url)
                ),
                caption=caption,
                parse_mode="HTML",
                reply_markup=markup,
            )
            return True
        except TelegramBadRequest as exc:
            logger.warning(
                "Cannot upload feed task %s preview as photo: %s", task.task_id, exc
            )
            return False

    try:
        await target.message.edit_media(
            media=InputMediaPhoto(
                media=task.result_url,
                caption=caption,
                parse_mode="HTML",
            ),
            reply_markup=markup,
        )
        return True
    except TelegramBadRequest as exc:
        logger.warning(
            "Cannot edit feed task %s by URL (%s); trying uploaded preview",
            task.task_id,
            exc,
        )

    image_bytes = await _download_preview(task.result_url)
    if not image_bytes:
        return False

    try:
        image_bytes = _prepare_preview_image(image_bytes)
        media = BufferedInputFile(
            image_bytes, filename=_filename_from_url(task.result_url)
        )
        await target.message.edit_media(
            media=InputMediaPhoto(media=media, caption=caption, parse_mode="HTML"),
            reply_markup=markup,
        )
        return True
    except TelegramBadRequest as exc:
        logger.warning(
            "Cannot edit feed task %s with uploaded preview (%s); replacing message",
            task.task_id,
            exc,
        )

    try:
        await target.message.delete()
    except TelegramBadRequest:
        pass

    try:
        await target.message.answer_photo(
            photo=BufferedInputFile(
                image_bytes, filename=_filename_from_url(task.result_url)
            ),
            caption=caption,
            parse_mode="HTML",
            reply_markup=markup,
        )
        return True
    except TelegramBadRequest as exc:
        logger.warning(
            "Cannot replace feed task %s with uploaded preview: %s", task.task_id, exc
        )
        return False


async def _show_feed(target, telegram_id: int, index: int = 0) -> None:
    cards = await get_feed_tasks(limit=30)
    if not cards:
        await _show_empty(target)
        return

    start_index = index % len(cards)
    for offset in range(len(cards)):
        current_index = (start_index + offset) % len(cards)
        task = cards[current_index]
        markup = get_feed_card_keyboard(
            task.task_id,
            index=current_index,
            is_owner=task.telegram_id == telegram_id,
        )
        if await _send_feed_photo(target, task, markup):
            if isinstance(target, types.CallbackQuery):
                await target.answer()
            return

    logger.warning("No feed cards with sendable photo previews were found")
    await _show_empty(target)


async def show_feed_task_by_id(message: types.Message, telegram_id: int, task_id: str) -> bool:
    task = await get_public_feed_task(task_id)
    if not task:
        return False
    return await _send_feed_photo(
        message,
        task,
        get_feed_card_keyboard(
            task.task_id, index=0, is_owner=task.telegram_id == telegram_id
        ),
    )


async def _feed_deep_link(bot, task_id: str) -> str:
    bot_info = await bot.get_me()
    return f"https://t.me/{bot_info.username}?start=feed_{task_id}"


@router.message(Command("feed"))
async def open_feed(message: types.Message, state: FSMContext):
    await state.clear()
    await _show_feed(message, message.from_user.id, index=0)


@router.callback_query(F.data == "menu_feed")
async def open_feed_from_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await _show_feed(callback, callback.from_user.id, index=0)


@router.callback_query(F.data.startswith("feed_next_"))
async def next_feed_card(callback: types.CallbackQuery):
    try:
        index = int(callback.data.replace("feed_next_", ""))
    except ValueError:
        index = 0
    await _show_feed(callback, callback.from_user.id, index=index)


@router.callback_query(F.data.startswith("feed_like_"))
async def like_feed_card(callback: types.CallbackQuery):
    payload = callback.data.replace("feed_like_", "", 1)
    try:
        task_id, index_raw = payload.rsplit("_", 1)
    except ValueError:
        await callback.answer("Не удалось поставить лайк", show_alert=True)
        return
    try:
        index = int(index_raw)
    except ValueError:
        index = 0

    likes = await like_feed_task(task_id, callback.from_user.id)
    if likes is None:
        await callback.answer("Пост уже недоступен", show_alert=True)
        return
    await callback.answer("❤️")
    await _show_feed(callback, callback.from_user.id, index=index)


@router.callback_query(F.data.startswith("feed_share_"))
async def share_feed_card(callback: types.CallbackQuery):
    task_id = callback.data.replace("feed_share_", "")
    task = await get_public_feed_task(task_id)
    if not task:
        await callback.answer("Пост уже недоступен", show_alert=True)
        return

    await increment_feed_share(task_id, callback.from_user.id)
    link = await _feed_deep_link(callback.bot, task_id)
    await callback.message.answer(
        "📤 <b>Ссылка на пост</b>\n\n"
        f"<code>{link}</code>",
        parse_mode="HTML",
    )
    await callback.answer("Ссылка готова")


@router.callback_query(F.data.startswith("feed_publish_"))
async def publish_task_to_feed(callback: types.CallbackQuery):
    task_id = callback.data.replace("feed_publish_", "")
    ok, reason = await share_task_to_feed(task_id, callback.from_user.id)
    if not ok:
        messages = {
            "not_found": "Не нашёл эту генерацию",
            "forbidden": "Это не ваша генерация",
            "not_ready": "В ленту можно добавить только готовое фото",
            "foreign_source": "Работу из чужой ленты нельзя публиковать как свою",
        }
        await callback.answer(messages.get(reason, "Не удалось добавить в ленту"), show_alert=True)
        return

    link = await _feed_deep_link(callback.bot, task_id)
    await callback.message.answer(
        "📤 <b>Фото добавлено в ленту</b>\n\n"
        f"🔗 Ссылка на пост:\n<code>{link}</code>",
        parse_mode="HTML",
    )
    await callback.answer("Добавлено в ленту")


@router.callback_query(F.data.startswith("feed_remove_"))
async def remove_feed_card(callback: types.CallbackQuery):
    payload = callback.data.replace("feed_remove_", "", 1)
    try:
        task_id, index_raw = payload.rsplit("_", 1)
    except ValueError:
        await callback.answer("Не удалось удалить пост", show_alert=True)
        return
    ok = await remove_task_from_feed(task_id, callback.from_user.id)
    if not ok:
        await callback.answer("Пост не найден или уже недоступен", show_alert=True)
        return
    await callback.answer("Удалено из ленты")
    await _show_feed(callback, callback.from_user.id, index=0)


@router.callback_query(F.data.startswith("feed_repeat_"))
async def repeat_feed_card(callback: types.CallbackQuery, state: FSMContext):
    task_id = callback.data.replace("feed_repeat_", "")
    task = await get_public_feed_task(task_id)
    if not task or not task.prompt:
        await callback.answer("Пост уже недоступен", show_alert=True)
        return

    await state.clear()
    await state.update_data(
        feed_retry_task_id=task_id,
        generation_type="image",
        reference_images=[],
        preset_id="feed_retry",
        img_service=task.model or "banana_pro",
        img_ratio=task.aspect_ratio or "1:1",
        img_count=1,
        img_options={},
        feed_retry_control_message_id=callback.message.message_id,
        feed_retry_prompt=task.prompt,
    )
    prompt_preview = html.escape(task.prompt)
    if len(prompt_preview) > 700:
        prompt_preview = prompt_preview[:700].rstrip() + "..."
    text = (
        "🔁 <b>Повторить генерацию</b>\n\n"
        "Промпт исходной работы будет применён к вашим референсам.\n\n"
        "📝 <b>Промпт (превью):</b>\n"
        f"<code>{prompt_preview}</code>\n\n"
        "Полный текст доступен по кнопке ниже.\n"
        "Загрузите свои фото-референсы, затем выберите модель и запустите повтор."
    )
    try:
        await callback.message.edit_caption(
            caption=text,
            parse_mode="HTML",
            reply_markup=get_reference_images_upload_keyboard(0, 14, "feed_retry"),
        )
    except TelegramBadRequest:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=get_reference_images_upload_keyboard(0, 14, "feed_retry"),
        )
    await state.set_state(GenerationStates.uploading_reference_images)
    await callback.answer()
