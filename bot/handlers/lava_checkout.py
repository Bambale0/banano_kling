from __future__ import annotations

import html
import logging
import re
import time
from typing import Any

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database import create_transaction, get_or_create_user
from bot.handlers.payments import (
    _get_selected_promo,
    _package_lava_offer_config,
    _promo_bonus_for_package,
)
from bot.keyboards import get_back_keyboard, get_payment_confirmation_keyboard
from bot.payment_utils import package_bonus_credits, total_package_credits
from bot.services.lava_service import lava_service
from bot.services.preset_manager import preset_manager
from bot.states import PaymentStates

logger = logging.getLogger(__name__)
router = Router()

LAVA_RUB_PAYMENT_PROVIDER = "PAY2ME"
LAVA_RUB_PAYMENT_METHOD = "SBP"
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
_BLOCKED_EMAIL_DOMAINS = {
    "example.com",
    "example.net",
    "example.org",
    "localhost",
    "invalid",
}
_BLOCKED_EMAILS = {
    "buyer@example.com",
    "client@example.com",
    "test@example.com",
}


def normalize_lava_customer_email(value: Any) -> str | None:
    """Validate a buyer email and reject placeholder/test addresses."""

    email = str(value or "").strip().lower()
    if not email or len(email) > 254 or not _EMAIL_RE.fullmatch(email):
        return None
    if email in _BLOCKED_EMAILS:
        return None
    domain = email.rsplit("@", 1)[-1]
    if domain in _BLOCKED_EMAIL_DOMAINS or domain.endswith(".invalid"):
        return None
    return email


def _email_request_keyboard() -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отменить оплату", callback_data="cancel_lava_email")
    return builder.as_markup()


def _format_lava_error(response: dict[str, Any] | None) -> str:
    data = response or {}
    error = data.get("error") or data.get("message") or data.get("raw")
    if isinstance(error, dict):
        error = error.get("message") or error.get("error") or str(error)
    return html.escape(str(error or "Lava не создала платёж"))[:700]


@router.callback_query(F.data.startswith("buy_lava_"))
async def request_lava_customer_email(
    callback: types.CallbackQuery,
    state: FSMContext,
) -> None:
    """Collect the actual buyer email before creating a Lava contract."""

    if not lava_service.enabled:
        await callback.message.edit_text(
            "Lava временно недоступна. Выберите другой способ оплаты.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        await callback.answer()
        return

    package_id = callback.data.replace("buy_lava_", "", 1)
    package = preset_manager.get_package(package_id)
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    offer_id, currency = _package_lava_offer_config(package)
    if not offer_id:
        await callback.message.edit_text(
            "Для этого пакета не настроен продукт Lava. Выберите другой способ оплаты.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        await callback.answer()
        return
    if str(currency or "").upper() != "RUB":
        logger.error(
            "Blocked non-RUB Lava checkout: package=%s currency=%s",
            package_id,
            currency,
        )
        await callback.message.edit_text(
            "Оплата Lava для этого пакета настроена не в рублях. "
            "Пожалуйста, выберите FreeKassa или напишите в поддержку.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        await callback.answer()
        return

    await state.update_data(lava_checkout_package_id=package_id)
    await state.set_state(PaymentStates.waiting_lava_email)
    await callback.message.edit_text(
        "📧 <b>Введите вашу электронную почту</b>\n\n"
        "Она будет передана Lava как почта конкретного покупателя и может "
        "использоваться для уведомления о платеже.\n\n"
        "Пример: <code>name@gmail.com</code>\n"
        "Не вводите чужую или тестовую почту.",
        reply_markup=_email_request_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_lava_email")
async def cancel_lava_email(
    callback: types.CallbackQuery,
    state: FSMContext,
) -> None:
    await state.clear()
    await callback.message.edit_text(
        "Оплата через Lava отменена.",
        reply_markup=get_back_keyboard("menu_topup"),
    )
    await callback.answer()


@router.message(PaymentStates.waiting_lava_email, F.text)
async def create_lava_sbp_checkout(
    message: types.Message,
    state: FSMContext,
) -> None:
    email = normalize_lava_customer_email(message.text)
    if not email:
        await message.answer(
            "Не получилось распознать реальную почту.\n"
            "Введите адрес в формате <code>name@gmail.com</code>. "
            "Тестовые адреса вроде <code>buyer@example.com</code> запрещены.",
            reply_markup=_email_request_keyboard(),
            parse_mode="HTML",
        )
        return

    state_data = await state.get_data()
    package_id = str(state_data.get("lava_checkout_package_id") or "").strip()
    package = preset_manager.get_package(package_id)
    if not package:
        await state.clear()
        await message.answer(
            "Пакет оплаты больше не найден. Выберите его заново.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        return

    offer_id, configured_currency = _package_lava_offer_config(package)
    currency = str(configured_currency or "").upper()
    if not offer_id or currency != "RUB":
        await state.clear()
        logger.error(
            "Invalid Lava RUB package configuration: package=%s offer=%s currency=%s",
            package_id,
            bool(offer_id),
            currency,
        )
        await message.answer(
            "Оплата Lava для этого пакета сейчас настроена некорректно. "
            "Выберите FreeKassa или обратитесь в поддержку.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        return

    promo = await _get_selected_promo(state)
    package_bonus = package_bonus_credits(package)
    promo_bonus = _promo_bonus_for_package(promo, package)
    total_credits = total_package_credits(package, promo_bonus)
    order_id = f"{message.from_user.id}_{int(time.time() * 1000)}_{package_id}"

    result = await lava_service.create_invoice(
        email=email,
        offer_id=offer_id,
        currency="RUB",
        payment_provider=LAVA_RUB_PAYMENT_PROVIDER,
        payment_method=LAVA_RUB_PAYMENT_METHOD,
        buyer_language="RU",
        client_utm={
            "telegram_id": str(message.from_user.id),
            "order_id": order_id,
            "package_id": package_id,
        },
    )
    if not result.get("ok"):
        await state.clear()
        logger.error(
            "Lava RUB/SBP invoice creation failed: user=%s package=%s status=%s error=%s",
            message.from_user.id,
            package_id,
            result.get("status"),
            _format_lava_error(result),
        )
        await message.answer(
            "Не удалось создать оплату через Lava.\n"
            f"Причина: <code>{_format_lava_error(result)}</code>",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        return

    invoice_id = lava_service.extract_invoice_id(result)
    payment_url = lava_service.extract_payment_url(result)
    if not invoice_id or not payment_url:
        await state.clear()
        logger.error(
            "Lava response has no invoice URL: user=%s package=%s",
            message.from_user.id,
            package_id,
        )
        await message.answer(
            "Lava не вернула ссылку на оплату. Выберите другой способ оплаты.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        return

    user = await get_or_create_user(message.from_user.id)
    created = await create_transaction(
        order_id=order_id,
        user_id=user.id,
        payment_id=str(invoice_id),
        provider="lava",
        credits=total_credits,
        amount_rub=float(package["price_rub"]),
        status="pending",
        promo_code_id=promo.id if promo and promo_bonus > 0 else None,
        promo_code=promo.code if promo and promo_bonus > 0 else None,
        promo_bonus_credits=promo_bonus,
    )
    if not created:
        await state.clear()
        await message.answer(
            "Платёж создан, но бот не смог сохранить заказ. "
            "Не оплачивайте эту ссылку и выберите пакет заново.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        return

    await state.clear()
    bonus_lines: list[str] = []
    if package_bonus > 0:
        bonus_lines.append(f"Бонус пакета: <code>{package_bonus}</code> бананов")
    if promo and promo_bonus > 0:
        bonus_lines.append(
            f"Промокод <code>{html.escape(promo.code)}</code>: "
            f"+<code>{promo_bonus}</code> бананов"
        )
    bonus_text = "\n" + "\n".join(bonus_lines) if bonus_lines else ""

    await message.answer(
        "💳 <b>Оплата через Lava · СБП</b>\n"
        f"• Пакет: <code>{html.escape(str(package['name']))}</code>\n"
        f"• Бананов: <code>{total_credits}</code>{bonus_text}\n"
        f"• Сумма: <code>{package['price_rub']}</code> ₽\n"
        f"• Почта покупателя: <code>{html.escape(email)}</code>\n\n"
        "Проверьте данные и перейдите к оплате.",
        reply_markup=get_payment_confirmation_keyboard(payment_url, order_id),
        parse_mode="HTML",
    )


@router.message(PaymentStates.waiting_lava_email)
async def reject_non_text_lava_email(message: types.Message) -> None:
    await message.answer(
        "Отправьте электронную почту обычным текстовым сообщением.",
        reply_markup=_email_request_keyboard(),
    )
