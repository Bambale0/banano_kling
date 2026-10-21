"""Bounded Telegram retries: retry ambiguous failures only for reads."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter

from bot.config import config

logger = logging.getLogger(__name__)
T = TypeVar('T')


async def telegram_api_call(
    operation: Callable[[], Awaitable[T]], *, retry_network: bool = False,
) -> T:
    attempts = max(1, min(5, config.TELEGRAM_TRANSIENT_MAX_ATTEMPTS))
    for attempt in range(attempts):
        try:
            return await operation()
        except TelegramRetryAfter as exc:
            delay = max(0, exc.retry_after)
            if delay > config.TELEGRAM_RETRY_AFTER_MAX_SECONDS or attempt + 1 >= attempts:
                raise
            logger.info('Telegram flood retry: attempt=%s delay_seconds=%s', attempt + 1, delay)
            await asyncio.sleep(delay)
        except (TelegramNetworkError, TimeoutError) as exc:
            if not retry_network or attempt + 1 >= attempts:
                raise
            logger.info('Telegram read retry: attempt=%s error_type=%s', attempt + 1, type(exc).__name__)
            await asyncio.sleep(2 ** attempt)
    raise AssertionError('unreachable')
