"""Deliver already-persisted Wan results; this module never starts a generation."""
from __future__ import annotations

import asyncio
import html
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramEntityTooLarge,
    TelegramRetryAfter,
)
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from bot.services.delivery_state import (
    telegram_media_too_large,
    terminal_telegram_delivery_reason,
)


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


def max_inline_video_bytes() -> int:
    """Conservative Telegram Bot API size threshold; configurable in environment."""
    try:
        return max(1, int(os.getenv("WAN3_TELEGRAM_MAX_INLINE_VIDEO_BYTES", "48000000")))
    except ValueError:
        return 48_000_000


def _explicit_media_too_large(exc: Exception) -> bool:
    # TelegramEntityTooLarge inherits TelegramNetworkError, not TelegramBadRequest.
    # An explicit size rejection is safe to follow with a link; a timeout is not.
    return isinstance(exc, TelegramEntityTooLarge) or telegram_media_too_large(exc)


def _managed_result_file(record: dict[str, Any]) -> tuple[Path, int] | None:
    """Only use retained results inside Wan's own managed directory."""
    path = record.get("result_path")
    if not path:
        return None
    try:
        local = Path(str(path)).resolve()
        local.relative_to(Path("static/uploads/wan3_prime/results").resolve())
        size = local.stat().st_size if local.is_file() else 0
        return (local, size) if size > 0 else None
    except (OSError, ValueError):
        return None


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
    from bot.services.original_download import original_download_url

    rows = []
    if url and urlsplit(url).scheme in {"http", "https"}:
        rows.append([InlineKeyboardButton(text="📥 Скачать оригинал", url=original_download_url(url))])
    rows.append([InlineKeyboardButton(text="🔁 Повторить / изменить", callback_data=f"wan3_recipe:{task_id}")])
    if url:
        rows.append([InlineKeyboardButton(text="🎞 В ленту", callback_data=f"feedpub_{task_id}")])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_download_link(
    bot: Any, telegram_id: int, caption: str, markup: InlineKeyboardMarkup,
    url: str, timeout: int, *, oversized: bool,
) -> DeliveryOutcome:
    if urlsplit(url).scheme not in {"http", "https"}:
        return DeliveryOutcome("pending", error="durable_result_unavailable")
    explanation = (
        "Файл слишком большой для отправки в Telegram — скачайте оригинал по кнопке ниже."
        if oversized else
        "Пока файл не удалось отправить в чат — оригинал доступен по кнопке ниже."
    )
    try:
        sent = await asyncio.wait_for(
            bot.send_message(
                telegram_id, caption + "\n\n" + explanation,
                parse_mode="HTML", reply_markup=markup,
            ),
            timeout=timeout,
        )
        return _receipt(sent, "link_sent")
    except Exception as exc:  # noqa: BLE001 - ambiguous responses stay uncertain
        return _failure(exc)


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

    if record.get("delivery_status") == "link_sent":
        return DeliveryOutcome("link_sent", error="download_link_already_sent")

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
    durable = _managed_result_file(record)
    # Preflight available local data; S3-only data is protected by the rejection fallback.
    if durable and durable[1] > max_inline_video_bytes():
        return await _send_download_link(
            bot, telegram_id, caption, markup, url, timeout, oversized=True,
        )
    if urlsplit(url).scheme in {"http", "https"}:
        try:
            sent = await asyncio.wait_for(bot.send_video(telegram_id, video=url,
                supports_streaming=True, **kwargs), timeout=timeout)
            return _receipt(sent)
        except Exception as exc:  # noqa: BLE001 - classify uncertain Telegram outcomes without replay
            if _explicit_media_too_large(exc):
                return await _send_download_link(
                    bot, telegram_id, caption, markup, url, timeout, oversized=True,
                )
            outcome = _failure(exc)
            if not isinstance(exc, TelegramBadRequest):
                return outcome
            if outcome.status == "unavailable":
                return outcome

    # Send only the durable file belonging to this task's managed result root.
    if durable:
        local, _size = durable
        try:
            sent = await asyncio.wait_for(bot.send_video(telegram_id,
                video=FSInputFile(local), supports_streaming=True, **kwargs), timeout=timeout)
            return _receipt(sent)
        except Exception as exc:  # noqa: BLE001 - classify uncertain Telegram outcomes without replay
            if _explicit_media_too_large(exc):
                return await _send_download_link(
                    bot, telegram_id, caption, markup, url, timeout, oversized=True,
                )
            outcome = _failure(exc)
            if not isinstance(exc, TelegramBadRequest) or outcome.status == "unavailable":
                return outcome
        # Keep the original quality if Telegram cannot stream this media.
        try:
            sent = await asyncio.wait_for(bot.send_document(telegram_id,
                document=FSInputFile(local), **kwargs), timeout=timeout)
            return _receipt(sent)
        except Exception as exc:  # noqa: BLE001 - classify uncertain Telegram outcomes without replay
            if _explicit_media_too_large(exc):
                return await _send_download_link(
                    bot, telegram_id, caption, markup, url, timeout, oversized=True,
                )
            outcome = _failure(exc)
            if not isinstance(exc, TelegramBadRequest) or outcome.status == "unavailable":
                return outcome

    return await _send_download_link(
        bot, telegram_id, caption, markup, url, timeout, oversized=False,
    )
