"""Enforce Telegram commerce at incoming update and outgoing Bot API seams."""
import logging
from urllib.parse import urlsplit

from aiogram import BaseMiddleware, types
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import config
from bot.payment_utils import package_stars_amount
from bot.services.preset_manager import preset_manager
from bot.states import PaymentStates
from bot.web_payments import payment_callback_target, web_payment_url

logger = logging.getLogger(__name__)


def website_keyboard(package_id: str = "", provider: str = "", *, promo_code: str = "") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Открыть оплату на сайте", url=web_payment_url(package_id, provider, promo_code=promo_code))],
        [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="menu_stars")],
    ])


class TelegramPaymentSurfaceMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        # Financial service updates must always reach the idempotent settlement
        # handler, regardless of a user's stale conversation state.
        if isinstance(event, types.Message) and event.successful_payment:
            return await handler(event, data)
        words = (event.text or '').split() if isinstance(event, types.Message) else []
        target = payment_callback_target(event.data or "") if isinstance(event, types.CallbackQuery) else None
        if isinstance(event, types.CallbackQuery) and event.data == "menu_stars":
            rows = []
            if config.TELEGRAM_STARS_ENABLED:
                for package in preset_manager.get_packages():
                    rows.append([InlineKeyboardButton(
                        text=f"{package['name']} · {package_stars_amount(package)}⭐",
                        callback_data=f"buy_stars_{package['id']}",
                    )])
            rows.append([InlineKeyboardButton(text="Оплата на сайте", url=web_payment_url())])
            await event.answer()
            if event.message:
                await event.message.answer("⭐ Выберите пакет Stars" if config.TELEGRAM_STARS_ENABLED else "Stars временно недоступны.", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
            return
        raw_state = data.get("raw_state")
        legacy_email = isinstance(event, types.Message) and raw_state == PaymentStates.waiting_lava_email.state
        command = words[0].split('@')[0] if words else ''
        deep_link = command in {"/balance", "/wallet", "/topup", "/pay"}
        if command == '/start' and len(words) > 1:
            argument = words[1]
            deep_link = argument in {"balance", "wallet", "topup", "payment", "pay"} or argument.startswith(("buy_", "choose_pay_"))
            if deep_link:
                target = payment_callback_target(argument)
        if target is not None or legacy_email or deep_link:
            state = data.get("state")
            payment_state = await state.get_data() if state is not None else {}
            if legacy_email and state is not None:
                target = (
                    str(payment_state.get("lava_checkout_package_id") or ""),
                    "lava_" + str(payment_state.get("lava_checkout_mode") or "sbp"),
                )
                await state.clear()
            message = event.message if isinstance(event, types.CallbackQuery) else event
            if isinstance(event, types.CallbackQuery):
                await event.answer()
            if message:
                await message.answer("Баланс и пополнение доступны на сайте. После входа вы вернётесь к оплате. В Telegram можно оплатить Stars.", reply_markup=website_keyboard(*(target or ("", "")), promo_code=str(payment_state.get("promo_code") or "")))
            return
        return await handler(event, data)


def website_payment_markup(markup: InlineKeyboardMarkup, *, promo_code: str = "") -> InlineKeyboardMarkup:
    rows = []
    redirected = False
    for row in markup.inline_keyboard:
        buttons = []
        for button in row:
            target = payment_callback_target(button.callback_data or "")
            url = urlsplit(button.url or (button.web_app.url if button.web_app else ""))
            # Tribute links are package-specific: preserve the product selection.
            if target is None and url.hostname == "web.tribute.tg":
                from bot.handlers.tribute_payments import TRIBUTE_PACKAGE_LINKS

                for package_id, configured_url in TRIBUTE_PACKAGE_LINKS.items():
                    configured = urlsplit(configured_url)
                    if url.hostname == configured.hostname and url.path.rstrip("/") == configured.path.rstrip("/"):
                        target = (package_id, "tribute")
                        break
            external_checkout = url.hostname in {
                "web.tribute.tg", "gate.lava.top", "pay.fk.money", "auth.robokassa.ru", "pay.crypt.bot",
            } or "/freekassa/checkout" in url.path
            if target is not None or external_checkout:
                redirected = True
                buttons.append(InlineKeyboardButton(text=button.text, url=web_payment_url(*(target or ("", "")), promo_code=promo_code)))
            else:
                buttons.append(button)
        rows.append(buttons)
    if not redirected:
        return markup
    has_stars = any((button.callback_data or '').startswith(('buy_stars_', 'menu_stars')) for row in rows for button in row)
    if redirected and config.TELEGRAM_STARS_ENABLED and not has_stars:
        rows.append([InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="menu_stars")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


class TelegramPaymentRequestMiddleware(BaseRequestMiddleware):
    def __init__(self):
        self.fsm = None

    async def __call__(self, make_request, bot, method):
        if method.__api_method__ in {"sendInvoice", "createInvoiceLink"} and method.currency != "XTR":
            raise ValueError("Telegram native payments require XTR")
        markup = getattr(method, "reply_markup", None)
        if isinstance(markup, InlineKeyboardMarkup):
            rewritten = website_payment_markup(markup)
            if rewritten is not markup:
                promo_code = ""
                chat_id = getattr(method, "chat_id", None)
                # In private chats the FSM is keyed by the user/chat ID.
                # Read only for a payment keyboard, never for ordinary replies.
                if self.fsm is not None and isinstance(chat_id, int) and chat_id > 0:
                    try:
                        state = self.fsm.get_context(bot=bot, chat_id=chat_id, user_id=chat_id)
                        stored = await state.get_data()
                        promo_code = str(stored.get("promo_code") or "")
                    except Exception as exc:
                        logger.warning("Payment promo lookup unavailable: error_type=%s", type(exc).__name__)
                if promo_code:
                    rewritten = website_payment_markup(markup, promo_code=promo_code)
                method = method.model_copy(update={"reply_markup": rewritten})
        return await make_request(bot, method)


def install_telegram_payment_surface(dp) -> None:
    from bot.handlers.payments import process_successful_stars_payment

    payment_surface = TelegramPaymentSurfaceMiddleware()
    dp.callback_query.outer_middleware(payment_surface)
    dp.message.outer_middleware(payment_surface)
    # Root observers run before generation/email FSM catch-all routers. A paid
    # invoice must settle even while the user is in an unrelated conversation.
    dp.message.register(
        process_successful_stars_payment,
        lambda message: message.successful_payment is not None,
    )
