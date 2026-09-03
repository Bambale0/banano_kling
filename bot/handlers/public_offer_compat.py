"""Exact local public-offer integration for Telegram payment and partner flows."""

from __future__ import annotations

import logging
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from aiogram import F, Router, types
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards import get_back_keyboard, get_partner_consent_keyboard

logger = logging.getLogger(__name__)
router = Router()

PUBLIC_OFFER_CALLBACK = "public_offer"
PUBLIC_OFFER_PDF_PATH = Path(__file__).resolve().parents[2] / "legal" / "public-offer.pdf"
PUBLIC_OFFER_TEXT_PATH = Path(__file__).resolve().parents[2] / "legal" / "public-offer.txt"


def _with_public_offer(markup: InlineKeyboardMarkup | None) -> InlineKeyboardMarkup | None:
    if markup is None:
        return None

    rows = [list(row) for row in markup.inline_keyboard]
    if any(
        button.callback_data in {PUBLIC_OFFER_CALLBACK, "partner_offer"}
        for row in rows
        for button in row
    ):
        return markup

    offer_row = [
        InlineKeyboardButton(
            text="📜 Оферта · оплата = согласие",
            callback_data=PUBLIC_OFFER_CALLBACK,
        )
    ]
    insert_at = len(rows)
    if rows:
        last_callbacks = {button.callback_data or "" for button in rows[-1]}
        if any(
            callback == "back_main"
            or callback == "menu_topup"
            or callback.startswith("back_")
            for callback in last_callbacks
        ):
            insert_at = len(rows) - 1
    rows.insert(insert_at, offer_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _wrap_keyboard(factory: Callable[..., Any]) -> Callable[..., Any]:
    if getattr(factory, "_public_offer_wrapped", False):
        return factory

    @wraps(factory)
    def wrapped(*args: Any, **kwargs: Any):
        return _with_public_offer(factory(*args, **kwargs))

    setattr(wrapped, "_public_offer_wrapped", True)
    return wrapped


def install_public_offer_compat(payments_module: Any) -> None:
    """Add the local offer to every shared Telegram payment keyboard."""
    import bot.keyboards as keyboard_module

    for name in (
        "get_payment_packages_keyboard",
        "get_payment_method_keyboard",
        "get_payment_confirmation_keyboard",
    ):
        current = getattr(keyboard_module, name, None)
        if not callable(current):
            continue
        wrapped = _wrap_keyboard(current)
        setattr(keyboard_module, name, wrapped)
        setattr(payments_module, name, wrapped)


async def _send_offer_text(
    callback: types.CallbackQuery,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    text = PUBLIC_OFFER_TEXT_PATH.read_text(encoding="utf-8")
    chunks = [text[index : index + 4000] for index in range(0, len(text), 4000)] or [text]
    for index, chunk in enumerate(chunks):
        await callback.message.answer(
            chunk,
            reply_markup=reply_markup if index == len(chunks) - 1 else None,
        )


@router.callback_query(F.data.in_({PUBLIC_OFFER_CALLBACK, "partner_offer"}))
async def show_public_offer(callback: types.CallbackQuery):
    """Send the exact locally bundled Prodamus offer, never an external URL."""
    if callback.message is None:
        await callback.answer("Оферта недоступна в этом сообщении", show_alert=True)
        return

    is_partner_flow = callback.data == "partner_offer"
    reply_markup = (
        get_partner_consent_keyboard()
        if is_partner_flow
        else get_back_keyboard("menu_topup")
    )

    try:
        await callback.message.answer_document(
            document=FSInputFile(
                str(PUBLIC_OFFER_PDF_PATH),
                filename="public-offer.pdf",
            ),
            caption="📜 Публичная оферта",
            reply_markup=reply_markup,
        )
    except Exception as exc:
        logger.exception("Failed to send bundled public offer PDF: %s", exc)
        await _send_offer_text(callback, reply_markup)

    await callback.answer()
