"""Deliver already-persisted Wan results; this module never starts a generation."""
from __future__ import annotations

import asyncio
import html
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from bot.services.delivery_state import terminal_telegram_delivery_reason


@dataclass(frozen=True)
class DeliveryOutcome:
    status: str
    message_id: int | None = None
    error: str | None = None
    retry_after: int = 300


def delivery_timeout() -> int:
    try:
        return max(10, min(300, int(os.getenv("WAN3_DELIVERY_TIMEOUT_SECONDS", "90"))))
    except ValueError:
        return 90


def _failure(exc: Exception) -> DeliveryOutcome:
    terminal = terminal_telegram_delivery_reason(exc)
    if terminal:
        return DeliveryOutcome("unavailable", error=terminal)
    if isinstance(exc, TelegramRetryAfter):
        return DeliveryOutcome("pending", error="telegram_rate_limit", retry_after=max(1, int(exc.retry_after)))
    if isinstance(exc, TelegramBadRequest):
        return DeliveryOutcome("pending", error="telegram_rejected_media")
    # A timeout or lost response may follow a successful Telegram send. Do not
    # duplicate it via a file fallback or automatic replay without a receipt.
    return DeliveryOutcome("uncertain", error=type(exc).__name__)


def _receipt(message: Any, status: str = "delivered") -> DeliveryOutcome:
    message_id = getattr(message, "message_id", None)
    if isinstance(message_id, int) and not isinstance(message_id, bool):
        return DeliveryOutcome(status, message_id=message_id)
    return DeliveryOutcome("uncertain", error="missing_telegram_receipt")


def _markup(task_id: str, url: str | None) -> InlineKeyboardMarkup:
    rows = []
    if url and urlsplit(url).scheme in {"http", "https"}:
        rows.append([InlineKeyboardButton(text="📥 Скачать оригинал", url=url)])
    rows.append([InlineKeyboardButton(text="🔁 Повторить / изменить", callback_data=f"wan3_recipe:{task_id}")])
    if url:
        rows.append([InlineKeyboardButton(text="🎞 В ленту", callback_data=f"feedpub_{task_id}")])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def deliver_wan_result(bot: Any, record: dict[str, Any]) -> DeliveryOutcome:
    from bot.services.wan3_models import wan3_model_spec

    label = wan3_model_spec(record.get("provider_model")).label
    task_id = str(record["internal_task_id"])
    telegram_id = int(record["telegram_id"])
    url = str(record.get("result_url") or "")
    timeout = delivery_timeout()
    if record["status"] == "failed":
        text = (f"❌ {label} не завершил генерацию.\n"
                f"🆔 <code>{html.escape(task_id)}</code>\n"
                f"Возвращено: <b>{float(record.get('refunded_credits') or 0):g}🍌</b>.")
        try:
            sent = await asyncio.wait_for(bot.send_message(telegram_id, text, parse_mode="HTML",
                reply_markup=_markup(task_id, None)), timeout=timeout)
            return _receipt(sent)
        except Exception as exc:  # noqa: BLE001 - classify uncertain Telegram outcomes without replay
            return _failure(exc)

    caption = (f"✅ <b>{label} — готово</b>\n"
               f"🆔 <code>{html.escape(task_id)}</code>\n"
               f"Списано: <b>{float(record.get('charged_credits') or 0):g}🍌</b>")
    refunded = float(record.get("refunded_credits") or 0)
    if refunded:
        caption += f"\nОстаток резерва возвращён: <b>{refunded:g}🍌</b>"
    seconds = record.get("result_seconds")
    if seconds is not None:
        caption += f"\nДлительность: <b>{float(seconds):g} с</b>"
    markup = _markup(task_id, url)
    kwargs = {"caption": caption, "parse_mode": "HTML", "reply_markup": markup}
    if urlsplit(url).scheme in {"http", "https"}:
        try:
            sent = await asyncio.wait_for(bot.send_video(telegram_id, video=url,
                supports_streaming=True, **kwargs), timeout=timeout)
            return _receipt(sent)
        except Exception as exc:  # noqa: BLE001 - classify uncertain Telegram outcomes without replay
            outcome = _failure(exc)
            if not isinstance(exc, TelegramBadRequest):
                return outcome
            if outcome.status == "unavailable":
                return outcome

    # Send only the durable file belonging to this task's managed result root.
    try:
        local = Path(str(record.get("result_path") or "")).resolve()
        local.relative_to(Path("static/uploads/wan3_prime/results").resolve())
        usable = local.is_file() and local.stat().st_size > 0
    except (OSError, ValueError):
        usable = False
    if usable:
        try:
            sent = await asyncio.wait_for(bot.send_video(telegram_id,
                video=FSInputFile(local), supports_streaming=True, **kwargs), timeout=timeout)
            return _receipt(sent)
        except Exception as exc:  # noqa: BLE001 - classify uncertain Telegram outcomes without replay
            outcome = _failure(exc)
            if not isinstance(exc, TelegramBadRequest) or outcome.status == "unavailable":
                return outcome
        # Keep the original quality if Telegram cannot stream this media.
        try:
            sent = await asyncio.wait_for(bot.send_document(telegram_id,
                document=FSInputFile(local), **kwargs), timeout=timeout)
            return _receipt(sent)
        except Exception as exc:  # noqa: BLE001 - classify uncertain Telegram outcomes without replay
            outcome = _failure(exc)
            if not isinstance(exc, TelegramBadRequest) or outcome.status == "unavailable":
                return outcome

    if record.get("delivery_status") == "link_sent":
        return DeliveryOutcome("link_sent", error="media_delivery_pending")
    if urlsplit(url).scheme not in {"http", "https"}:
        return DeliveryOutcome("pending", error="durable_result_unavailable")
    try:
        sent = await asyncio.wait_for(bot.send_message(telegram_id,
            caption + "\n\nВидео готово. Пока файл не удалось отправить в чат — оригинал доступен по кнопке ниже.",
            parse_mode="HTML", reply_markup=markup), timeout=timeout)
        return _receipt(sent, "link_sent")
    except Exception as exc:  # noqa: BLE001 - classify uncertain Telegram outcomes without replay
        return _failure(exc)
