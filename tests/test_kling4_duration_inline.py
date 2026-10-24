"""Duration buttons update their existing Telegram card."""

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText

from bot.handlers import kling4
from tests import test_kling4_navigation as navigation_tests

telegram = navigation_tests.telegram
lifecycle_boundary = navigation_tests.lifecycle_boundary


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "duration,delta,expected",
    [(5, 1, 6), (11, -1, 10), (3, -1, 3), (30, 1, 30), (11, 0, 11)],
)
async def test_duration_edits_card_without_sending(telegram, duration, delta, expected):
    state, message, query = telegram
    recipe = kling4.fresh()
    recipe["input"]["duration"] = duration
    await kling4.save(state, recipe)
    query.data = f"k4:duration:{delta}"
    await kling4.callback(query, state)
    message.answer.assert_not_awaited()
    message.edit_text.assert_awaited_once()
    assert (await state.get_data())["k4_recipe"]["input"]["duration"] == expected
    assert f"{expected}с" in message.edit_text.await_args.args[0]
    query.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_unchanged_duration_does_not_send_fallback(telegram):
    state, message, query = telegram
    await kling4.save(state, kling4.fresh())
    message.edit_text.side_effect = TelegramBadRequest(
        method=EditMessageText(chat_id=1, message_id=2, text="same"),
        message="Bad Request: message is not modified",
    )
    query.data = "k4:duration:0"
    await kling4.callback(query, state)
    message.answer.assert_not_awaited()
    message.edit_text.assert_awaited_once()
    query.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_other_edit_errors_are_not_hidden_or_duplicated(telegram):
    state, message, query = telegram
    await kling4.save(state, kling4.fresh())
    message.edit_text.side_effect = TelegramBadRequest(
        method=EditMessageText(chat_id=1, message_id=2, text="changed"),
        message="Bad Request: message to edit not found",
    )
    query.data = "k4:duration:1"
    with pytest.raises(TelegramBadRequest):
        await kling4.callback(query, state)
    message.answer.assert_not_awaited()
