"""High-priority Telegram browser approval handlers.

This router must be included BEFORE generation FSM routers so a website
login deep link cannot accidentally be consumed as a text prompt.
"""
from __future__ import annotations

from aiogram import F, Router, types

from bot.database import get_or_create_user, mark_telegram_chat_available
from bot.telegram_browser_approval import decide, send_confirmation

router = Router(name="telegram_browser_approval")

# Telegram deep links allow at most 64 URL-safe characters; auth_ + 43 fits.
@router.message(F.text.regexp(r"^/start(?:@[A-Za-z0-9_]{5,32})? auth_[A-Za-z0-9_-]{43}$"))
async def browser_login_start(message: types.Message) -> None:
    if not message.from_user or message.chat.type != "private" or not message.text:
        return
    telegram_id = message.from_user.id
    await get_or_create_user(telegram_id)
    await mark_telegram_chat_available(telegram_id)
    from bot.handlers.common import _sync_telegram_profile

    await _sync_telegram_profile(message.from_user)
    secret = message.text.split(" auth_", 1)[1]
    await send_confirmation(message, secret)


@router.callback_query(F.data.regexp(r"^wba:(?:yes|no):[A-Za-z0-9_-]{43}$"))
async def browser_login_confirmation(callback: types.CallbackQuery) -> None:
    await decide(callback)
