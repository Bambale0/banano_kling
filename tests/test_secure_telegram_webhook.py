import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest

from bot.config import config
from bot.services import telegram_webhook_runtime as runtime


SECRET = "secure_telegram_webhook_secret_1234567890"


class FakeRequest:
    def __init__(self, payload, *, secret=SECRET, content_length=None):
        if isinstance(payload, bytes):
            self._body = payload
        else:
            self._body = json.dumps(payload).encode("utf-8")
        self.headers = {
            "X-Telegram-Bot-Api-Secret-Token": secret,
        }
        self.content_length = (
            len(self._body) if content_length is None else content_length
        )

    async def read(self):
        return self._body


async def _prepare(monkeypatch, **env):
    await runtime.reset_runtime_for_tests()
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_QUEUE_SIZE", "8")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_WORKERS", "1")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_MAX_BODY_BYTES", "1048576")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_DEDUPE_TTL_SECONDS", "3600")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_LOCAL_DEDUPE_LIMIT", "100")
    for name, value in env.items():
        monkeypatch.setenv(name, str(value))
    monkeypatch.setattr(
        runtime.redis_service,
        "get_client",
        AsyncMock(return_value=None),
    )
    runtime._settings_cache = None


@pytest.mark.asyncio
async def test_rejects_missing_or_invalid_secret(monkeypatch):
    await _prepare(monkeypatch)
    dispatcher = Mock(feed_update=AsyncMock())
    bot = Mock()

    missing = FakeRequest({"update_id": 1}, secret="")
    invalid = FakeRequest({"update_id": 2}, secret="wrong-secret")

    assert (await runtime.handle_secure_telegram_webhook(missing, bot, dispatcher)).status == 403
    assert (await runtime.handle_secure_telegram_webhook(invalid, bot, dispatcher)).status == 403
    dispatcher.feed_update.assert_not_awaited()

    await runtime.reset_runtime_for_tests()


@pytest.mark.asyncio
async def test_valid_update_is_processed_by_bounded_worker(monkeypatch):
    await _prepare(monkeypatch)
    dispatcher = Mock(feed_update=AsyncMock())
    bot = Mock()

    response = await runtime.handle_secure_telegram_webhook(
        FakeRequest({"update_id": 101}),
        bot,
        dispatcher,
    )

    assert response.status == 200
    assert runtime._queue is not None
    await asyncio.wait_for(runtime._queue.join(), timeout=1)
    dispatcher.feed_update.assert_awaited_once()
    processed_update = dispatcher.feed_update.await_args.args[1]
    assert processed_update.update_id == 101

    await runtime.reset_runtime_for_tests()


@pytest.mark.asyncio
async def test_duplicate_update_id_is_not_processed_twice(monkeypatch):
    await _prepare(monkeypatch)
    dispatcher = Mock(feed_update=AsyncMock())
    bot = Mock()
    request = FakeRequest({"update_id": 202})

    first = await runtime.handle_secure_telegram_webhook(request, bot, dispatcher)
    second = await runtime.handle_secure_telegram_webhook(
        FakeRequest({"update_id": 202}),
        bot,
        dispatcher,
    )

    assert first.status == 200
    assert second.status == 200
    assert runtime._queue is not None
    await asyncio.wait_for(runtime._queue.join(), timeout=1)
    dispatcher.feed_update.assert_awaited_once()

    await runtime.reset_runtime_for_tests()


@pytest.mark.asyncio
async def test_rejects_oversized_body_before_parsing(monkeypatch):
    await _prepare(monkeypatch, TELEGRAM_WEBHOOK_MAX_BODY_BYTES=1024)
    dispatcher = Mock(feed_update=AsyncMock())
    bot = Mock()

    response = await runtime.handle_secure_telegram_webhook(
        FakeRequest(b"x" * 1025),
        bot,
        dispatcher,
    )

    assert response.status == 413
    dispatcher.feed_update.assert_not_awaited()

    await runtime.reset_runtime_for_tests()


@pytest.mark.asyncio
async def test_returns_503_when_queue_capacity_is_exhausted(monkeypatch):
    await _prepare(
        monkeypatch,
        TELEGRAM_WEBHOOK_QUEUE_SIZE=1,
        TELEGRAM_WEBHOOK_WORKERS=1,
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_feed_update(_bot, _update):
        started.set()
        await release.wait()

    dispatcher = Mock(feed_update=AsyncMock(side_effect=blocked_feed_update))
    bot = Mock()

    first = await runtime.handle_secure_telegram_webhook(
        FakeRequest({"update_id": 301}), bot, dispatcher
    )
    assert first.status == 200
    await asyncio.wait_for(started.wait(), timeout=1)

    second = await runtime.handle_secure_telegram_webhook(
        FakeRequest({"update_id": 302}), bot, dispatcher
    )
    overloaded = await runtime.handle_secure_telegram_webhook(
        FakeRequest({"update_id": 303}), bot, dispatcher
    )

    assert second.status == 200
    assert overloaded.status == 503
    assert overloaded.headers["Retry-After"] == "1"

    release.set()
    assert runtime._queue is not None
    await asyncio.wait_for(runtime._queue.join(), timeout=1)
    assert dispatcher.feed_update.await_count == 2

    await runtime.reset_runtime_for_tests()


@pytest.mark.asyncio
async def test_startup_registers_webhook_with_secret_token(monkeypatch):
    await _prepare(monkeypatch)
    legacy_startup = AsyncMock()
    monkeypatch.setattr(runtime, "_legacy_on_startup", legacy_startup)

    original_host = config.WEBHOOK_HOST
    original_path = config.WEBHOOK_PATH
    config.WEBHOOK_HOST = "https://example.test"
    config.WEBHOOK_PATH = "/telegram/webhook"

    bot = SimpleNamespace(set_webhook=AsyncMock())
    dispatcher = Mock(
        feed_update=AsyncMock(),
        resolve_used_update_types=Mock(return_value=["message", "callback_query"]),
    )

    try:
        await runtime.secure_on_startup(bot, dispatcher=dispatcher)
    finally:
        config.WEBHOOK_HOST = original_host
        config.WEBHOOK_PATH = original_path

    legacy_startup.assert_awaited_once_with(bot, dispatcher=dispatcher)
    bot.set_webhook.assert_awaited_once_with(
        "https://example.test/telegram/webhook",
        secret_token=SECRET,
        allowed_updates=["message", "callback_query"],
    )

    await runtime.reset_runtime_for_tests()


def test_bot_token_derived_secret_is_stable_and_not_the_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:TEST_TOKEN")
    runtime._settings_cache = None

    first = runtime.load_settings().secret
    runtime._settings_cache = None
    second = runtime.load_settings().secret

    assert first == second
    assert first != config.BOT_TOKEN
    assert len(first) == 64
