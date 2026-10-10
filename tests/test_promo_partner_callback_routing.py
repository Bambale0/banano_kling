"""Telegram dispatcher regression: promo callbacks must not be mistaken for partner rates."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import AnswerCallbackQuery, EditMessageText

from bot.handlers import admin as admin_handlers
from bot.handlers import partner_rate_admin, promo_admin


@pytest.mark.asyncio
async def test_promo_history_and_draft_open_reach_promo_router(monkeypatch):
    """Replicate the production router order and the promo-history buttons."""
    campaign = {
        "id": 26,
        "revision": 3,
        "status": "completed",
        "message": {"text": "Новый тренд", "parse_mode": "HTML", "media": [], "buttons": []},
        "ready": False,
        "content_hash": "saved",
        "tested_content_hash": None,
        "test_summary": None,
    }
    service = SimpleNamespace(
        PromoError=ValueError,
        list_promos=AsyncMock(return_value=[campaign]),
        get_promo=AsyncMock(return_value=campaign),
    )
    monkeypatch.setattr(promo_admin, "_service", lambda: service)
    monkeypatch.setattr(promo_admin.config, "is_admin", lambda user_id: user_id == 999999999)

    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(partner_rate_admin.router)
    dispatcher.include_router(admin_handlers.router)
    bot = Bot("123456:TEST_TOKEN_FOR_CI_ONLY")
    user = types.User(id=999999999, is_bot=False, first_name="Admin")
    menu = types.Message(
        message_id=100,
        date=datetime.now(timezone.utc),
        chat=types.Chat(id=user.id, type="private"),
        from_user=types.User(id=123456, is_bot=True, first_name="Bot"),
        text="Promos",
    )
    transport = AsyncMock(return_value=menu)
    monkeypatch.setattr(bot.session, "make_request", transport)

    async def click(update_id, data):
        await dispatcher.feed_update(
            bot,
            types.Update(
                update_id=update_id,
                callback_query=types.CallbackQuery(
                    id=str(update_id), from_user=user, chat_instance="test", message=menu, data=data,
                ),
            ),
        )

    try:
        await click(1, "admin_pr:list:0")
        await click(2, "admin_pr:open:26")

        service.list_promos.assert_awaited_once()
        service.get_promo.assert_awaited_once_with(26, user.id)
        state = dispatcher.fsm.get_context(bot=bot, chat_id=user.id, user_id=user.id)
        assert (await state.get_data())["promo_id"] == 26

        sent_methods = [
            method
            for call in transport.await_args_list
            for method in call.args
            if isinstance(method, (EditMessageText, AnswerCallbackQuery))
        ]
        edits = [method.text for method in sent_methods if isinstance(method, EditMessageText)]
        assert any("Черновики и история" in text for text in edits)
        assert any("Промо #26" in text for text in edits)
        assert all(
            not (method.show_alert and "проценты партнёров" in (method.text or ""))
            for method in sent_methods if isinstance(method, AnswerCallbackQuery)
        )
    finally:
        await bot.session.close()
        await dispatcher.storage.close()
        for router in dispatcher.sub_routers:
            router._parent_router = None
        dispatcher.sub_routers.clear()
