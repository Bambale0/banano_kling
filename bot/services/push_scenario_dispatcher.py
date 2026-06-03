from __future__ import annotations

import asyncio
import html
import logging
from typing import Protocol

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import config
from bot import database
from bot.services.push_scenario_service import (
    PushScenarioEvent,
    PushScenarioService,
    push_scenario_service,
)

logger = logging.getLogger(__name__)


class MessageBot(Protocol):
    async def send_message(self, chat_id: int, text: str, **kwargs) -> object:
        ...


def build_push_scenario_text(event: PushScenarioEvent) -> str:
    lines = [f"🔔 <b>{html.escape(event.title)}</b>", "", html.escape(event.message)]

    bonus = int(event.payload.get("bonus_credits") or 0)
    if bonus > 0:
        lines.extend(["", f"🪙 Бонус уже начислен: <b>{bonus}</b>"])

    promo_code = event.payload.get("promo_code")
    if promo_code:
        lines.extend(["", f"🎟 Промокод: <code>{html.escape(str(promo_code))}</code>"])

    return "\n".join(lines)


def build_push_scenario_keyboard(event: PushScenarioEvent) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Открыть бот", callback_data="back_main")],
    ]
    if event.scenario_key == "payment_abandoned" or event.payload.get("package_code"):
        rows.insert(
            0,
            [InlineKeyboardButton(text="Купить BoomCoin", callback_data="menu_topup")],
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def apply_push_scenario_side_effects(event: PushScenarioEvent) -> None:
    bonus = int(event.payload.get("bonus_credits") or 0)
    if bonus <= 0:
        return

    await database.add_credits_once(
        event.telegram_id,
        bonus,
        reason="push_scenario_bonus",
        external_id=event.event_key,
        metadata={
            "scenario_key": event.scenario_key,
            "event_key": event.event_key,
        },
    )


async def send_push_scenario_event(
    bot: MessageBot,
    event: PushScenarioEvent,
    service: PushScenarioService = push_scenario_service,
    *,
    user_cooldown_seconds: int = 86400,
) -> bool:
    if await service.was_user_contacted_recently(
        event.telegram_id, cooldown_seconds=user_cooldown_seconds
    ):
        logger.info(
            "Push scenario skipped by cooldown: scenario=%s telegram_id=%s",
            event.scenario_key,
            event.telegram_id,
        )
        return False

    try:
        await apply_push_scenario_side_effects(event)
        await bot.send_message(
            chat_id=event.telegram_id,
            text=build_push_scenario_text(event),
            reply_markup=build_push_scenario_keyboard(event),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except TelegramForbiddenError:
        logger.info(
            "Push scenario user blocked bot: scenario=%s telegram_id=%s",
            event.scenario_key,
            event.telegram_id,
        )
        await service.mark_event_sent(event)
        return False
    except TelegramBadRequest as exc:
        message = str(exc).lower()
        if any(
            marker in message
            for marker in ("chat not found", "user is deactivated", "bot was blocked")
        ):
            logger.info(
                "Push scenario terminal Telegram error: scenario=%s telegram_id=%s error=%s",
                event.scenario_key,
                event.telegram_id,
                exc,
            )
            await service.mark_event_sent(event)
            return False
        logger.warning(
            "Push scenario Telegram error, will retry later: scenario=%s telegram_id=%s error=%s",
            event.scenario_key,
            event.telegram_id,
            exc,
        )
        return False
    except Exception:
        logger.exception(
            "Push scenario send failed, will retry later: scenario=%s telegram_id=%s",
            event.scenario_key,
            event.telegram_id,
        )
        return False

    await service.mark_event_sent(event)
    await service.mark_user_contacted(event.telegram_id)
    logger.info(
        "Push scenario sent: scenario=%s telegram_id=%s event_key=%s",
        event.scenario_key,
        event.telegram_id,
        event.event_key,
    )
    return True


async def dispatch_due_push_scenarios(
    bot: MessageBot,
    service: PushScenarioService = push_scenario_service,
    *,
    limit: int = 50,
    sleep_seconds: float = 0.2,
    user_cooldown_seconds: int = 86400,
) -> dict[str, int]:
    events = await service.collect_due_events(limit=limit)
    sent = 0
    failed = 0
    skipped = 0

    for event in events:
        if await service.was_user_contacted_recently(
            event.telegram_id, cooldown_seconds=user_cooldown_seconds
        ):
            skipped += 1
            logger.info(
                "Push scenario skipped by cooldown: scenario=%s telegram_id=%s",
                event.scenario_key,
                event.telegram_id,
            )
            continue

        if await send_push_scenario_event(
            bot,
            event,
            service,
            user_cooldown_seconds=user_cooldown_seconds,
        ):
            sent += 1
        else:
            failed += 1
        if sleep_seconds > 0:
            await asyncio.sleep(sleep_seconds)

    return {"due": len(events), "sent": sent, "failed": failed, "skipped": skipped}


async def push_scenario_background_loop(
    bot: MessageBot,
    service: PushScenarioService = push_scenario_service,
    *,
    interval_seconds: int = 600,
    batch_limit: int = 50,
    sleep_seconds: float = 0.2,
    user_cooldown_seconds: int = 86400,
    startup_delay_seconds: int = 0,
) -> None:
    interval_seconds = max(30, int(interval_seconds))
    batch_limit = max(1, int(batch_limit))
    startup_delay_seconds = max(0, int(startup_delay_seconds))

    logger.info(
        "Push scenario background loop started: interval=%ss limit=%s startup_delay=%ss cooldown=%ss",
        interval_seconds,
        batch_limit,
        startup_delay_seconds,
        user_cooldown_seconds,
    )

    if startup_delay_seconds:
        await asyncio.sleep(startup_delay_seconds)

    while True:
        try:
            stats = await dispatch_due_push_scenarios(
                bot,
                service,
                limit=batch_limit,
                sleep_seconds=sleep_seconds,
                user_cooldown_seconds=user_cooldown_seconds,
            )
            if stats["due"]:
                logger.info("Push scenario batch finished: %s", stats)
        except asyncio.CancelledError:
            logger.info("Push scenario background loop cancelled")
            raise
        except Exception:
            logger.exception("Push scenario background iteration failed")

        await asyncio.sleep(interval_seconds)
