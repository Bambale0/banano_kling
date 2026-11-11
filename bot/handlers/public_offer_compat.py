"""Public-offer attachment callbacks for Telegram More, payments and partners."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router, types
from aiogram.types import InlineKeyboardMarkup

from bot.config import config
from bot.keyboards import get_back_keyboard, get_partner_consent_keyboard
from bot.legal_documents import legal_document_attachment

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


def install_public_offer_compat(payments_module: Any) -> None:
    """Keep legacy callback routes without modifying the payment handlers."""
    _ = payments_module


async def _send_offer_document(
    callback: types.CallbackQuery,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    """Deliver the bundled public-offer PDF as a Telegram document."""
    attachment = legal_document_attachment("offer")
    await callback.message.answer_document(
        attachment,
        caption="📜 Публичная оферта",
        reply_markup=reply_markup,
        parse_mode=None,
    )


@router.callback_query(F.data.in_(PUBLIC_OFFER_CALLBACKS))
async def show_public_offer(callback: types.CallbackQuery):
    """Serve the offer as a file, even if an HTTPS URL was configured."""
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
        logger.debug("Telegram offer attachment takes precedence over configured URL")

    # Acknowledge the callback before uploading the PDF.
    await callback.answer()
    try:
        await _send_offer_document(callback, reply_markup)
    except (OSError, ValueError):
        logger.exception("The public-offer PDF is missing or invalid")
        await callback.message.answer(
            "Не удалось открыть оферту. Обратитесь в поддержку."
        )
    except Exception:
        logger.exception("Failed to send public offer document")
        await callback.message.answer(
            "Не удалось отправить оферту файлом. Попробуйте снова."
        )
