"""Wan 3.0 delivery: oversize media must yield one durable download link."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramEntityTooLarge
from aiogram.methods import SendVideo

from bot import database
from bot.services.wan3_prime_delivery import deliver_wan_result
from bot.services.wan3_prime_lifecycle import Wan3PrimeLifecycle
from tests.test_wan3_prime_lifecycle import Prices, Probe, Provider, body, user_actor


def _record(**overrides):
    record = {
        "internal_task_id": "wan3_oversize_test",
        "telegram_id": 12345,
        "status": "completed",
        "provider_model": "wan/3-0-video-prime",
        "result_url": "https://neuromixbot.com/uploads/wan3_prime/results/wan3_oversize_test.mp4",
        "result_path": "static/uploads/wan3_prime/results/missing.mp4",
        "charged_credits": 180,
        "result_seconds": 30,
    }
    record.update(overrides)
    return record


def _bot(*, video_error=None):
    return SimpleNamespace(
        send_video=AsyncMock(
            side_effect=video_error,
            return_value=SimpleNamespace(message_id=88),
        ),
        send_document=AsyncMock(return_value=SimpleNamespace(message_id=89)),
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=90)),
    )


def _download_button(bot):
    markup = bot.send_message.await_args.kwargs["reply_markup"]
    return next(b for row in markup.inline_keyboard for b in row if b.text == "📥 Скачать оригинал")


@pytest.mark.asyncio
async def test_telegram_entity_too_large_sends_download_link_instead_of_uncertain():
    error = TelegramEntityTooLarge(
        method=SendVideo(chat_id=12345, video="https://example.org/result.mp4"),
        message="Request Entity Too Large",
    )
    bot = _bot(video_error=error)

    outcome = await deliver_wan_result(bot, _record())

    assert outcome.status == "link_sent"
    assert outcome.message_id == 90
    bot.send_video.assert_awaited_once()
    bot.send_document.assert_not_awaited()
    bot.send_message.assert_awaited_once()
    assert _download_button(bot).url == _record()["result_url"]


@pytest.mark.asyncio
async def test_explicit_bad_request_file_too_big_also_sends_link():
    error = TelegramBadRequest(
        method=SendVideo(chat_id=12345, video="https://example.org/result.mp4"),
        message="Bad Request: file is too big",
    )
    bot = _bot(video_error=error)

    outcome = await deliver_wan_result(bot, _record())

    assert outcome.status == "link_sent"
    bot.send_document.assert_not_awaited()
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_oversize_local_result_sends_link_before_any_media_upload(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "static/uploads/wan3_prime/results/oversize.mp4"
    path.parent.mkdir(parents=True)
    with path.open("wb") as output:
        output.truncate(61_054_548)
    bot = _bot()

    outcome = await deliver_wan_result(bot, _record(result_path=str(path)))

    assert outcome.status == "link_sent"
    bot.send_video.assert_not_awaited()
    bot.send_document.assert_not_awaited()
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_normal_video_still_delivered_inline():
    bot = _bot()

    outcome = await deliver_wan_result(bot, _record())

    assert outcome.status == "delivered"
    bot.send_video.assert_awaited_once()
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_ambiguous_network_failure_never_sends_duplicate_link():
    bot = _bot(video_error=TimeoutError("lost response after sending"))

    outcome = await deliver_wan_result(bot, _record())

    assert outcome.status == "uncertain"
    bot.send_message.assert_not_awaited()
    bot.send_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_link_receipt_does_not_resend_video_or_link():
    bot = _bot()

    outcome = await deliver_wan_result(bot, _record(delivery_status="link_sent"))

    assert outcome.status == "link_sent"
    bot.send_video.assert_not_awaited()
    bot.send_document.assert_not_awaited()
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmed_link_is_not_retried_by_recovery_poller():
    """Delivery receipt is terminal: never repeat media or charge again."""
    actor = await user_actor(credits=50)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=provider)
    quote = await lifecycle.quote(actor, body())
    submitted = await lifecycle.launch(actor, body(), quote, "wan3-link-terminal")
    task_id = submitted["task_id"]

    async with database.db_backend.connect(database.DATABASE_PATH) as conn:
        await conn.execute(
            "UPDATE wan3_prime_intents SET status = 'completed', settled = 1, "
            "delivery_status = 'link_sent', result_url = ?, next_attempt_at = CURRENT_TIMESTAMP "
            "WHERE internal_task_id = ?",
            ("https://neuromixbot.com/uploads/wan3_prime/results/test.mp4", task_id),
        )
        await conn.commit()

    bot = _bot()
    assert await lifecycle.deliver_ready_once(bot) == 0
    assert await lifecycle.deliver_ready_once(bot) == 0
    bot.send_video.assert_not_awaited()
    bot.send_document.assert_not_awaited()
    bot.send_message.assert_not_awaited()
    assert provider.creates == 1
