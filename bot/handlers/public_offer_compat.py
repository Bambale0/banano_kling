"""Public-offer text callbacks for Telegram More, payments and partners."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from aiogram import F, Router, types
from aiogram.types import InlineKeyboardMarkup

from bot.config import config
from bot.keyboards import get_back_keyboard, get_partner_consent_keyboard
from bot.legal_documents import send_legal_parts, telegram_text_parts

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
    """Keep legacy callback routes without modifying the payment handlers."""
    _ = payments_module


async def _send_offer_text(
    callback: types.CallbackQuery,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    """Deliver the complete approved offer in ordered UTF-16-safe text parts."""
    chunks = telegram_text_parts(PUBLIC_OFFER_TEXT_PATH.read_text(encoding="utf-8"))
    if not chunks:
        raise ValueError("Bundled public offer is empty")
    await send_legal_parts(callback.message, chunks, reply_markup)


@router.callback_query(F.data.in_(PUBLIC_OFFER_CALLBACKS))
async def show_public_offer(callback: types.CallbackQuery):
    """Show the full bundled offer in chat instead of sending a PDF or a URL."""
    if callback.message is None:
        await callback.answer("Оферта недоступна в этом сообщении", show_alert=True)
        return

    if callback.data == "partner_offer":
        reply_markup = get_partner_consent_keyboard()
    elif callback.data == MORE_PUBLIC_OFFER_CALLBACK:
        reply_markup = get_back_keyboard("ux_more")
    else:
        reply_markup = get_back_keyboard("menu_topup")

    if config.PARTNER_OFFER_URL:
        logger.debug("Telegram offer uses full local text regardless of configured URL")

    # Acknowledge the callback before streaming the multi-message legal text.
    await callback.answer()
    try:
        await _send_offer_text(callback, reply_markup)
    except (OSError, ValueError):
        logger.exception("Bundled public offer text is missing or invalid")
        await callback.message.answer(
            "Не удалось открыть оферту. Обратитесь в поддержку."
        )
    except Exception:
        logger.exception("Failed to deliver full public offer text")
        await callback.message.answer(
            "Не удалось полностью показать оферту. Попробуйте снова."
        )
