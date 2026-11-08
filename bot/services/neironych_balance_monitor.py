"""Periodic Neironych RUB balance checks with Redis-backed admin alert deduplication.

The upstream /v1/balance contract reports cash in balance_rub. Do not use
available_balance_rub: it can include a credit limit and mask a top-up need.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import aiohttp
from aiogram import Bot

from bot.config import config
from bot.services.redis_service import RedisService, redis_service

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.xn--e1aikcel5c5a.online"
_RELEASE_CLAIM_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""
_MONITOR_TASK: asyncio.Task[None] | None = None


def parse_balance_rub(payload: Any) -> Decimal:
    """Accept only an unambiguous finite RUB string, never a credit balance."""
    if not isinstance(payload, dict):
        raise ValueError("Neironych balance response must be a JSON object")
    raw = payload.get("balance_rub")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Neironych balance_rub must be a non-empty decimal string")
    try:
        amount = Decimal(raw.strip())
    except InvalidOperation as exc:
        raise ValueError("Neironych balance_rub is not a decimal") from exc
    if not amount.is_finite():
        raise ValueError("Neironych balance_rub is not finite")
    return amount


@dataclass(frozen=True)
class BalanceAlertSettings:
    api_key: str
    base_url: str
    admin_ids: tuple[int, ...]
    threshold_rub: Decimal
    interval_seconds: int
    reminder_seconds: int
    timeout_seconds: float

    @classmethod
    def from_environment(cls) -> BalanceAlertSettings | None:
        if os.getenv("NEIRONYCH_BALANCE_ALERT_ENABLED", "1").lower() in {
            "0", "false", "off", "no"
        }:
            return None

        key = os.getenv("NEIRONYCH_API_KEY", "").strip()
        admins = tuple(sorted({admin for admin in config.admin_ids if admin > 0}))
        if not key or not admins:
            logger.warning(
                "event=neironych_balance_monitor_disabled reason=%s",
                "missing_api_key" if not key else "missing_admin_ids",
            )
            return None

        base = os.getenv("NEIRONYCH_API_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")
        parsed = urlparse(base)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("NEIRONYCH_API_BASE_URL must be an HTTPS origin without credentials")

        try:
            threshold = Decimal(os.getenv("NEIRONYCH_BALANCE_ALERT_THRESHOLD_RUB", "2000"))
            interval = int(os.getenv("NEIRONYCH_BALANCE_ALERT_INTERVAL_SECONDS", "900"))
            reminder = int(os.getenv("NEIRONYCH_BALANCE_ALERT_REMINDER_SECONDS", "43200"))
            timeout = float(os.getenv("NEIRONYCH_BALANCE_ALERT_TIMEOUT_SECONDS", "10"))
        except (ValueError, InvalidOperation) as exc:
            raise ValueError("Invalid Neironych balance alert configuration") from exc
        if (
            not threshold.is_finite() or threshold <= 0
            or not 60 <= interval <= 86400
            or not interval <= reminder <= 604800
            or not 1 <= timeout <= 60
        ):
            raise ValueError("Neironych balance alert configuration is out of range")
        return cls(
            api_key=key,
            base_url=base,
            admin_ids=admins,
            threshold_rub=threshold,
            interval_seconds=interval,
            reminder_seconds=reminder,
            timeout_seconds=timeout,
        )


class BalanceMonitor:
    def __init__(
        self,
        bot: Bot,
        settings: BalanceAlertSettings,
        *,
        cache: RedisService = redis_service,
    ) -> None:
        self.bot = bot
        self.settings = settings
        self.cache = cache

    async def fetch_balance(self) -> Decimal:
        """Read-only call; retry once for transient failures and never log the key."""
        url = f"{self.settings.base_url}/v1/balance"
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Accept": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=self.settings.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in range(2):
                try:
                    async with session.get(
                        url, headers=headers, allow_redirects=False
                    ) as response:
                        if response.status != 200:
                            if (response.status == 429 or response.status >= 500) and attempt == 0:
                                await asyncio.sleep(1)
                                continue
                            raise ValueError(
                                f"Neironych balance endpoint returned HTTP {response.status}"
                            )
                        return parse_balance_rub(await response.json())
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    if attempt:
                        raise RuntimeError(
                            "Neironych balance endpoint unavailable"
                        ) from exc
                    await asyncio.sleep(1)
        raise RuntimeError("Neironych balance endpoint unavailable")

    def _alert_key(self, admin_id: int) -> str:
        return self.cache.build_key(f"neironych:balance_alert:{admin_id}")

    async def check_once(self) -> Decimal:
        balance = await self.fetch_balance()
        threshold = self.settings.threshold_rub
        logger.info(
            "event=neironych_balance_checked status=ok below_threshold=%s",
            balance < threshold,
        )
        client = await self.cache.get_client()
        if client is None:
            logger.warning("event=neironych_balance_alert_deferred reason=redis_unavailable")
            return balance

        if balance >= threshold:
            # A successful healthy reading rearms the next threshold crossing.
            for admin_id in self.settings.admin_ids:
                await client.delete(self._alert_key(admin_id))
            return balance

        display_balance = f"{balance:,.2f}".replace(",", " ").replace(".", ",")
        display_threshold = f"{threshold:,.2f}".replace(",", " ").replace(".", ",")
        message = (
            "⚠️ Нейроныч: низкий баланс API\n\n"
            f"Остаток: {display_balance} ₽\n"
            f"Порог: {display_threshold} ₽\n\n"
            "Пополните баланс провайдера, чтобы генерации не останавливались."
        )

        for admin_id in self.settings.admin_ids:
            key = self._alert_key(admin_id)
            claim = uuid4().hex
            # SET NX with a TTL is atomic across instances/restarts.
            acquired = await client.set(
                key, claim, ex=self.settings.reminder_seconds, nx=True
            )
            if not acquired:
                continue
            try:
                await self.bot.send_message(
                    chat_id=admin_id, text=message, parse_mode=None
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "event=neironych_balance_alert_send_failed admin_id=%s error_type=%s",
                    admin_id, type(exc).__name__,
                )
                try:
                    # Never release another worker's newer claim.
                    await client.eval(_RELEASE_CLAIM_SCRIPT, 1, key, claim)
                except Exception:
                    logger.exception(
                        "event=neironych_balance_claim_release_failed admin_id=%s",
                        admin_id,
                    )
            else:
                logger.info(
                    "event=neironych_balance_alert_sent admin_id=%s",
                    admin_id,
                )
        return balance

    async def run(self) -> None:
        while True:
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("event=neironych_balance_check_failed")
            await asyncio.sleep(self.settings.interval_seconds)


def ensure_neironych_balance_monitor(bot: Bot) -> None:
    global _MONITOR_TASK
    if _MONITOR_TASK is not None and not _MONITOR_TASK.done():
        return
    try:
        settings = BalanceAlertSettings.from_environment()
    except ValueError:
        logger.exception("event=neironych_balance_monitor_invalid_configuration")
        return
    if settings is None:
        return
    _MONITOR_TASK = asyncio.create_task(
        BalanceMonitor(bot, settings).run(), name="neironych-balance-monitor"
    )
    logger.info(
        "event=neironych_balance_monitor_started interval_seconds=%s",
        settings.interval_seconds,
    )


async def stop_neironych_balance_monitor() -> None:
    global _MONITOR_TASK
    task = _MONITOR_TASK
    _MONITOR_TASK = None
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
