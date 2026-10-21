from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import GetFile, SendDocument

from bot.handlers import generation
from bot.services.telegram_transport import telegram_api_call


@pytest.mark.asyncio
async def test_explicit_flood_rejection_waits_then_sends_once(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr('bot.services.telegram_transport.asyncio.sleep', sleep)
    operation = AsyncMock(side_effect=[TelegramRetryAfter(method=SendDocument(chat_id=1, document='file'), message='flood', retry_after=5), 'sent'])
    assert await telegram_api_call(operation) == 'sent'
    assert operation.await_count == 2
    sleep.assert_awaited_once_with(5)


@pytest.mark.asyncio
async def test_ambiguous_send_network_failure_is_never_retried():
    operation = AsyncMock(side_effect=TelegramNetworkError(method=GetFile(file_id='file'), message='timeout'))
    with pytest.raises(TelegramNetworkError):
        await telegram_api_call(operation)
    assert operation.await_count == 1


@pytest.mark.asyncio
async def test_reference_download_recovers_from_telegram_timeout(monkeypatch):
    monkeypatch.setattr('bot.services.telegram_transport.asyncio.sleep', AsyncMock())
    error = TelegramNetworkError(method=GetFile(file_id='file'), message='timeout')
    bot = SimpleNamespace(get_file=AsyncMock(side_effect=[error, SimpleNamespace(file_path='ref.jpg')]), download_file=AsyncMock(return_value=BytesIO(b'jpeg')))
    message = SimpleNamespace(bot=bot, photo=[SimpleNamespace(file_id='file')], document=None, from_user=SimpleNamespace(id=123))
    # Image validation is downstream; successful transport reaches it after retry.
    result = await generation._save_reference_image_from_message(message)
    assert bot.get_file.await_count == 2
    bot.download_file.assert_awaited_once_with('ref.jpg')
    assert result[0] is None
    assert 'скачать' not in result[1]


@pytest.mark.asyncio
async def test_transient_read_retries_are_bounded(monkeypatch):
    monkeypatch.setattr('bot.services.telegram_transport.asyncio.sleep', AsyncMock())
    operation = AsyncMock(side_effect=TelegramNetworkError(method=GetFile(file_id='file'), message='timeout'))
    with pytest.raises(TelegramNetworkError):
        await telegram_api_call(operation, retry_network=True)
    assert operation.await_count == 3
