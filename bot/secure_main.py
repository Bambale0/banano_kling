from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Update

from bot import main as legacy_main
from bot.config import config
from bot.services.redis_service import redis_service

logger = logging.getLogger(__name__)

_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
_DERIVATION_CONTEXT = b"banano-kling:telegram-webhook:v1"


@dataclass(frozen=True)
class TelegramWebhookSettings:
    secret: str
    queue_size: int
    workers: int
    max_body_bytes: int
    dedupe_ttl_seconds: int
    local_dedupe_limit: int


def _bounded_env_int(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def _resolve_webhook_secret() -> str:
    explicit = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if explicit:
        if not _SECRET_PATTERN.fullmatch(explicit):
            raise RuntimeError(
                "TELEGRAM_WEBHOOK_SECRET must contain 32-256 characters: "
                "A-Z, a-z, 0-9, underscore or hyphen"
            )
        return explicit

    bot_token = str(config.BOT_TOKEN or "").strip()
    if not bot_token:
        raise RuntimeError(
            "TELEGRAM_WEBHOOK_SECRET is not configured and BOT_TOKEN is unavailable"
        )

    # A deterministic HMAC-derived fallback prevents an unsafe deployment when
    # the new environment variable has not been provisioned yet. Operators can
    # override it with TELEGRAM_WEBHOOK_SECRET and rotate independently later.
    derived = hmac.new(
        bot_token.encode("utf-8"),
        _DERIVATION_CONTEXT,
        hashlib.sha256,
    ).hexdigest()
    logger.warning(
        "TELEGRAM_WEBHOOK_SECRET is not set; using a BOT_TOKEN-derived secret. "
        "Set an explicit secret to allow independent rotation."
    )
    return derived


def _load_settings() -> TelegramWebhookSettings:
    return TelegramWebhookSettings(
        secret=_resolve_webhook_secret(),
        queue_size=_bounded_env_int(
            "TELEGRAM_WEBHOOK_QUEUE_SIZE", 256, minimum=1, maximum=10_000
        ),
        workers=_bounded_env_int(
            "TELEGRAM_WEBHOOK_WORKERS", 4, minimum=1, maximum=32
        ),
        max_body_bytes=_bounded_env_int(
            "TELEGRAM_WEBHOOK_MAX_BODY_BYTES",
            1024 * 1024,
            minimum=1024,
            maximum=8 * 1024 * 1024,
        ),
        dedupe_ttl_seconds=_bounded_env_int(
            "TELEGRAM_WEBHOOK_DEDUPE_TTL_SECONDS",
            24 * 60 * 60,
            minimum=60,
            maximum=7 * 24 * 60 * 60,
        ),
        local_dedupe_limit=_bounded_env_int(
            "TELEGRAM_WEBHOOK_LOCAL_DEDUPE_LIMIT",
            20_000,
            minimum=100,
            maximum=200_000,
        ),
    )


@dataclass(frozen=True)
class _QueuedUpdate:
    update: Update


@dataclass(frozen=True)
class _DedupeReservation:
    backend: str
    key: str


_queue: asyncio.Queue[_QueuedUpdate | None] | None = None
_workers: list[asyncio.Task[None]] = []
_runtime_bot: Bot | None = None
_runtime_dispatcher: Dispatcher | None = None
_runtime_lock = asyncio.Lock()
_local_dedupe_lock = asyncio.Lock()
_local_dedupe: OrderedDict[int, float] = OrderedDict()

_legacy_on_startup = legacy_main.on_startup
_legacy_on_shutdown = legacy_main.on_shutdown


def _is_ignored_telegram_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(
        fragment in message
        for fragment in (
            "chat not found",
            "bot was blocked",
            "user is deactivated",
            "query is too old",
            "query id is invalid",
        )
    )


async def _worker_loop(worker_number: int) -> None:
    while True:
        queue = _queue
        bot = _runtime_bot
        dispatcher = _runtime_dispatcher
        if queue is None or bot is None or dispatcher is None:
            return

        item = await queue.get()
        try:
            if item is None:
                return
            await dispatcher.feed_update(bot, item.update)
        except asyncio.CancelledError:
            raise
        except TelegramBadRequest as error:
            if _is_ignored_telegram_error(error):
                logger.info(
                    "Telegram webhook worker %s ignored stale/unavailable chat error: %s",
                    worker_number,
                    error,
                )
            else:
                logger.exception(
                    "Telegram API error in webhook worker %s", worker_number
                )
        except Exception:
            logger.exception("Telegram webhook worker %s failed", worker_number)
        finally:
            queue.task_done()


async def _ensure_runtime(bot: Bot, dispatcher: Dispatcher) -> None:
    global _queue, _runtime_bot, _runtime_dispatcher

    async with _runtime_lock:
        if _queue is not None:
            if _runtime_bot is not bot or _runtime_dispatcher is not dispatcher:
                raise RuntimeError("Telegram webhook runtime is already bound")
            return

        settings = _load_settings()
        _runtime_bot = bot
        _runtime_dispatcher = dispatcher
        _queue = asyncio.Queue(maxsize=settings.queue_size)
        _workers.extend(
            asyncio.create_task(
                _worker_loop(index + 1),
                name=f"telegram-webhook-worker-{index + 1}",
            )
            for index in range(settings.workers)
        )
        logger.info(
            "Telegram webhook queue started: workers=%s capacity=%s",
            settings.workers,
            settings.queue_size,
        )


async def _stop_runtime(*, drain: bool = True) -> None:
    global _queue, _runtime_bot, _runtime_dispatcher

    async with _runtime_lock:
        queue = _queue
        workers = list(_workers)
        if queue is None:
            return

        if drain:
            try:
                await asyncio.wait_for(queue.join(), timeout=20)
            except asyncio.TimeoutError:
                logger.warning(
                    "Telegram webhook queue did not drain before shutdown; "
                    "cancelling remaining workers"
                )

        for _ in workers:
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                break

        if workers:
            done, pending = await asyncio.wait(workers, timeout=10)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                if task.cancelled():
                    continue
                error = task.exception()
                if error:
                    logger.error("Telegram webhook worker stopped with error: %s", error)

        _workers.clear()
        _queue = None
        _runtime_bot = None
        _runtime_dispatcher = None


async def _reserve_local_update(
    update_id: int,
    settings: TelegramWebhookSettings,
) -> _DedupeReservation | None:
    now = time.monotonic()
    expires_at = now + settings.dedupe_ttl_seconds

    async with _local_dedupe_lock:
        while _local_dedupe:
            first_update_id, first_expiry = next(iter(_local_dedupe.items()))
            if first_expiry > now and len(_local_dedupe) <= settings.local_dedupe_limit:
                break
            _local_dedupe.pop(first_update_id, None)

        existing_expiry = _local_dedupe.get(update_id)
        if existing_expiry and existing_expiry > now:
            return None

        _local_dedupe[update_id] = expires_at
        _local_dedupe.move_to_end(update_id)
        while len(_local_dedupe) > settings.local_dedupe_limit:
            _local_dedupe.popitem(last=False)

    return _DedupeReservation("local", str(update_id))


async def _reserve_update(
    update_id: int,
    settings: TelegramWebhookSettings,
) -> _DedupeReservation | None:
    redis_key = redis_service.build_key(f"telegram:update:{update_id}")
    client = await redis_service.get_client()
    if client is not None:
        try:
            reserved = await client.set(
                redis_key,
                "1",
                ex=settings.dedupe_ttl_seconds,
                nx=True,
            )
            if not reserved:
                return None
            return _DedupeReservation("redis", redis_key)
        except Exception:
            logger.exception(
                "Redis Telegram update dedupe failed; falling back to local cache"
            )

    return await _reserve_local_update(update_id, settings)


async def _release_reservation(reservation: _DedupeReservation) -> None:
    if reservation.backend == "redis":
        await redis_service.delete(reservation.key)
        return

    try:
        update_id = int(reservation.key)
    except ValueError:
        return
    async with _local_dedupe_lock:
        _local_dedupe.pop(update_id, None)


def _secret_is_valid(request: web.Request, expected_secret: str) -> bool:
    received = request.headers.get(_SECRET_HEADER, "")
    return bool(received) and hmac.compare_digest(received, expected_secret)


async def handle_secure_telegram_webhook(
    request: web.Request,
    bot: Bot,
    dispatcher: Dispatcher,
) -> web.Response:
    try:
        settings = _load_settings()
    except RuntimeError:
        logger.exception("Telegram webhook security settings are invalid")
        return web.json_response({"error": "service_unavailable"}, status=503)

    if not _secret_is_valid(request, settings.secret):
        logger.warning("Rejected Telegram webhook with invalid secret token")
        return web.json_response({"error": "forbidden"}, status=403)

    content_length = getattr(request, "content_length", None)
    if content_length is not None and content_length > settings.max_body_bytes:
        return web.json_response({"error": "payload_too_large"}, status=413)

    raw_body = await request.read()
    if not raw_body:
        return web.json_response({"error": "empty_body"}, status=400)
    if len(raw_body) > settings.max_body_bytes:
        return web.json_response({"error": "payload_too_large"}, status=413)

    try:
        update_data: Any = json.loads(raw_body.decode("utf-8"))
        if not isinstance(update_data, dict):
            raise TypeError("Telegram Update must be an object")
        update = Update(**update_data)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Rejected malformed Telegram webhook payload")
        return web.json_response({"error": "invalid_update"}, status=400)

    await _ensure_runtime(bot, dispatcher)
    reservation = await _reserve_update(update.update_id, settings)
    if reservation is None:
        return web.Response(text="OK", status=200)

    queue = _queue
    if queue is None:
        await _release_reservation(reservation)
        return web.json_response({"error": "service_unavailable"}, status=503)

    try:
        queue.put_nowait(_QueuedUpdate(update=update))
    except asyncio.QueueFull:
        await _release_reservation(reservation)
        logger.warning(
            "Telegram webhook queue is full: capacity=%s update_id=%s",
            settings.queue_size,
            update.update_id,
        )
        return web.json_response(
            {"error": "temporarily_overloaded"},
            status=503,
            headers={"Retry-After": "1"},
        )

    return web.Response(text="OK", status=200)


async def secure_on_startup(
    bot: Bot,
    dispatcher: Dispatcher | None = None,
) -> None:
    settings = _load_settings()
    if dispatcher is not None:
        await _ensure_runtime(bot, dispatcher)

    # Prevent the legacy startup hook from briefly registering a webhook
    # without secret_token. All other startup work remains unchanged.
    webhook_host = config.WEBHOOK_HOST
    if webhook_host:
        config.WEBHOOK_HOST = ""
    try:
        await _legacy_on_startup(bot, dispatcher=dispatcher)
    finally:
        config.WEBHOOK_HOST = webhook_host

    if webhook_host:
        webhook_kwargs: dict[str, Any] = {"secret_token": settings.secret}
        if dispatcher is not None:
            webhook_kwargs["allowed_updates"] = dispatcher.resolve_used_update_types()
        await bot.set_webhook(config.webhook_url, **webhook_kwargs)
        logger.info("Telegram webhook registered with secret token")


async def secure_on_shutdown(bot: Bot) -> None:
    await _stop_runtime()
    await _legacy_on_shutdown(bot)


async def _reset_runtime_for_tests() -> None:
    await _stop_runtime(drain=False)
    async with _local_dedupe_lock:
        _local_dedupe.clear()


# Patch only the runtime seams needed by bot.main. This keeps the emergency
# security fix isolated from the large legacy module while preserving all
# existing handlers, routes and background jobs.
legacy_main.handle_telegram_webhook = handle_secure_telegram_webhook
legacy_main.on_startup = secure_on_startup
legacy_main.on_shutdown = secure_on_shutdown


if __name__ == "__main__":
    asyncio.run(legacy_main.main())
