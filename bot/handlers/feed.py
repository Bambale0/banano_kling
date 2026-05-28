import logging

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

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
)

logger = logging.getLogger(__name__)
router = Router()


def _feed_caption(task) -> str:
    author = f"user {task.telegram_id}" if task.telegram_id else "anon"
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


async def _show_feed(target, telegram_id: int, index: int = 0) -> None:
    cards = await get_feed_tasks(limit=30)
    if not cards:
        await _show_empty(target)
        return

    index = index % len(cards)
    task = cards[index]
    markup = get_feed_card_keyboard(
        task.task_id,
        index=index,
        is_owner=task.telegram_id == telegram_id,
    )
    caption = _feed_caption(task)
    if isinstance(target, types.CallbackQuery):
        await target.message.answer_photo(
            photo=task.result_url,
            caption=caption,
            parse_mode="HTML",
            reply_markup=markup,
        )
        await target.answer()
    else:
        await target.answer_photo(
            photo=task.result_url,
            caption=caption,
            parse_mode="HTML",
            reply_markup=markup,
        )


async def show_feed_task_by_id(message: types.Message, telegram_id: int, task_id: str) -> bool:
    task = await get_public_feed_task(task_id)
    if not task:
        return False
    await message.answer_photo(
        photo=task.result_url,
        caption=_feed_caption(task),
        parse_mode="HTML",
        reply_markup=get_feed_card_keyboard(
            task.task_id,
            index=0,
            is_owner=task.telegram_id == telegram_id,
        ),
    )
    return True


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
        task_id, _index_raw = payload.rsplit("_", 1)
    except ValueError:
        await callback.answer("Не удалось поставить лайк", show_alert=True)
        return
    try:
        index = int(index_raw)
    except ValueError:
        index = 0

    likes = await like_feed_task(task_id)
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

    await increment_feed_share(task_id)
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
async def repeat_feed_card(callback: types.CallbackQuery):
    task_id = callback.data.replace("feed_repeat_", "")
    task = await get_public_feed_task(task_id)
    if not task or not task.prompt:
        await callback.answer("Пост уже недоступен", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="🔁 Запустить повтор", callback_data=f"retry_img_{task_id}")
    builder.button(text="🔥 Вернуться в ленту", callback_data="menu_feed")
    builder.adjust(1)
    await callback.message.answer(
        "🔁 <b>Повторить генерацию</b>\n\n"
        "Промпт исходной работы сохранён внутри бота и не показывается в карточке. "
        "Можно запустить повтор тем же генераторным путём.",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()
