"""Measure background webhook backlog separately from Telegram HTTP 200."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import main


@pytest.mark.asyncio
async def test_queue_wait_and_handler_runtime_are_logged(monkeypatch, caplog):
    semaphore = asyncio.Semaphore(1)
    await semaphore.acquire()
    monkeypatch.setattr(main, "_TELEGRAM_WEBHOOK_SEMAPHORE", semaphore)
    monkeypatch.setattr(main.config, "TELEGRAM_WEBHOOK_QUEUE_WARN_MS", 1.0)
    monkeypatch.setattr(main.config, "TELEGRAM_HANDLER_SLOW_WARN_MS", 1.0)

    async def handle(_bot, _update):
        await asyncio.sleep(0.025)

    dispatcher = SimpleNamespace(feed_update=handle)
    request = SimpleNamespace(read=AsyncMock(return_value=b'{"update_id": 7123456}'))
    caplog.set_level(logging.WARNING, logger="bot.main")

    response = await main.handle_telegram_webhook(request, object(), dispatcher)
    assert response.status == 200
    assert not any("Telegram update processing slow" in r.message for r in caplog.records)
    try:
        await asyncio.sleep(0.025)
    finally:
        semaphore.release()

    await asyncio.wait_for(
        asyncio.gather(*list(main._TELEGRAM_WEBHOOK_TASKS)), timeout=0.5
    )
    queued = [r.message for r in caplog.records if "Telegram webhook queue slow" in r.message]
    handled = [
        r.message for r in caplog.records
        if "Telegram update processing slow" in r.message
    ]
    assert len(queued) == 1
    assert len(handled) == 1
    assert "update_id=7123456" in queued[0]
    assert "queue_wait_ms=" in handled[0]
    assert "handler_ms=" in handled[0]
