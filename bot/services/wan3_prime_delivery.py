"""Deliver already-persisted Wan results; this module never starts a generation."""
from __future__ import annotations

import asyncio
import html
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import aiohttp
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from bot.services.delivery_state import terminal_telegram_delivery_reason
from bot.services.media_input_utils import is_local_upload_source


async def _download_owned_retry_media(url: str, task_id: str) -> Path | None:
    """Transient direct-upload source for a completed, owned Wan result.

    A remote Telegram URL fetch already had an ambiguous outcome; a later
    scheduled attempt uploads bytes from our own S3-backed media endpoint.
    No arbitrary external links or local cache retention are permitted.
    """
    path = urlsplit(url).path
    if (
        not is_local_upload_source(url)
        or not path.startswith("/uploads/wan3_prime/results/")
        or not path.endswith(f"/{task_id}.mp4")
    ):
        return None
    try:
        max_bytes = max(1024 * 1024, int(os.getenv("WAN3_REDELIVERY_MAX_BYTES", "52428800")))
    except ValueError:
        max_bytes = 52428800
    fd, tmp_name = tempfile.mkstemp(prefix="wan3_retry_", suffix=".mp4")
    os.close(fd)
    result = Path(tmp_name)
    total = 0
    try:
        timeout = aiohttp.ClientTimeout(total=120, connect=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as response:
                response.raise_for_status()
                with result.open("wb") as file:
                    async for chunk in response.content.iter_chunked(262144):
                        total += len(chunk)
                        if total > max_bytes:
                            raise ValueError("wan3_retry_media_too_large")
                        file.write(chunk)
        if total < 1024:
            raise ValueError("wan3_retry_media_empty")
        return result
    except Exception:
        result.unlink(missing_ok=True)
        raise


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
    if record.get("delivery_status") == "uncertain":
        # Retry only after the scheduled backoff and a fenced DB lease. An
        # unknown previous receipt may have succeeded, so no immediate
        # fallback is sent after a transient Telegram error.
        try:
            retry_file = await _download_owned_retry_media(url, task_id)
        except Exception as exc:  # noqa: BLE001 - keep the result for future retries
            return DeliveryOutcome("pending", error=f"retry_download_{type(exc).__name__}")
        if retry_file is None:
            return DeliveryOutcome("pending", error="trusted_retry_result_unavailable")
        try:
            try:
                sent = await asyncio.wait_for(bot.send_video(
                    telegram_id, video=FSInputFile(retry_file),
                    supports_streaming=True, **kwargs,
                ), timeout=timeout)
                return _receipt(sent)
            except Exception as exc:  # noqa: BLE001 - retry document only on explicit rejection
                outcome = _failure(exc)
                if not isinstance(exc, TelegramBadRequest) or outcome.status == "unavailable":
                    return outcome
            try:
                sent = await asyncio.wait_for(bot.send_document(
                    telegram_id, document=FSInputFile(retry_file), **kwargs,
                ), timeout=timeout)
                return _receipt(sent)
            except Exception as exc:  # noqa: BLE001
                return _failure(exc)
        finally:
            retry_file.unlink(missing_ok=True)
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
