"""Exact public-offer integration for Telegram More and legacy partner callbacks."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from aiogram import F, Router, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import config
from bot.keyboards import get_back_keyboard, get_partner_consent_keyboard
from bot.legal_documents import https_document_url, send_legal_parts, telegram_text_parts

logger = logging.getLogger(__name__)
router = Router()

PUBLIC_OFFER_CALLBACK = "public_offer"
MORE_PUBLIC_OFFER_CALLBACK = "more_public_offer"
PUBLIC_OFFER_CALLBACKS = {
    PUBLIC_OFFER_CALLBACK,
    MORE_PUBLIC_OFFER_CALLBACK,
    "partner_offer",
    "payment_public_offer",
}
PUBLIC_OFFER_TEXT_PATH = Path(__file__).resolve().parents[2] / "legal" / "public-offer.txt"


def install_public_offer_compat(payments_module: Any) -> None:
    """Keep the established offer callback routes without payment monkey-patching."""
    _ = payments_module


async def _send_offer_text(
    callback: types.CallbackQuery,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    """Deliver every character of the full local offer in plain UTF-16-safe parts."""
    chunks = telegram_text_parts(PUBLIC_OFFER_TEXT_PATH.read_text(encoding="utf-8"))
    if not chunks:
        raise ValueError("Bundled public offer is empty")
    await send_legal_parts(callback.message, chunks, reply_markup)


@router.callback_query(F.data.in_(PUBLIC_OFFER_CALLBACKS))
async def show_public_offer(callback: types.CallbackQuery):
    """Serve the full offer by verified-format HTTPS URL or Telegram plain text."""
    if callback.message is None:
        await callback.answer("Оферта недоступна в этом сообщении", show_alert=True)
        return

    is_partner_flow = callback.data == "partner_offer"
    if is_partner_flow:
        reply_markup = get_partner_consent_keyboard()
    elif callback.data == MORE_PUBLIC_OFFER_CALLBACK:
        reply_markup = get_back_keyboard("ux_more")
    else:
        reply_markup = get_back_keyboard("menu_topup")

    offer_url = https_document_url(config.PARTNER_OFFER_URL)
    if config.PARTNER_OFFER_URL and offer_url is None:
        logger.warning("Ignoring invalid public offer URL; falling back to local text")

    # Telegram callback queries expire quickly; acknowledge before streaming
    # the long offer. Delivery continues in chat after the spinner is cleared.
    await callback.answer()
    try:
        if offer_url:
            url_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔗 Открыть оферту", url=offer_url)],
                    *reply_markup.inline_keyboard,
                ],
            )
            await callback.message.answer(
                "📜 Публичная оферта\n\nПолный текст доступен по ссылке.",
                reply_markup=url_keyboard,
                parse_mode=None,
            )
        else:
            await _send_offer_text(callback, reply_markup)
    except (OSError, ValueError):
        logger.exception("The public offer is missing or invalid")
        await callback.message.answer(
            "Не удалось открыть оферту. Обратитесь в поддержку."
        )
        return
    except Exception:
        logger.exception("Failed to deliver public offer as text or link")
        await callback.message.answer(
            "Не удалось полностью показать оферту. Попробуйте снова."
        )
        return

