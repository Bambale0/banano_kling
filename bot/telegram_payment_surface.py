"""Enforce Telegram commerce at incoming update and outgoing Bot API seams."""
from urllib.parse import urlsplit

from aiogram import BaseMiddleware, types
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import config
from bot.payment_utils import package_stars_amount
from bot.services.preset_manager import preset_manager
from bot.states import PaymentStates
from bot.web_payments import payment_callback_target, web_payment_url


def website_keyboard(package_id: str = "", provider: str = "") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Открыть оплату на сайте", url=web_payment_url(package_id, provider))],
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
            if legacy_email and data.get("state"):
                await data["state"].clear()
            message = event.message if isinstance(event, types.CallbackQuery) else event
            if isinstance(event, types.CallbackQuery):
                await event.answer()
            if message:
                await message.answer("Баланс и пополнение доступны на сайте. После входа вы вернётесь к оплате. В Telegram можно оплатить Stars.", reply_markup=website_keyboard(*(target or ("", ""))))
            return
        return await handler(event, data)


def website_payment_markup(markup: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    rows = []
    redirected = False
    for row in markup.inline_keyboard:
        buttons = []
        for button in row:
            target = payment_callback_target(button.callback_data or "")
            url = urlsplit(button.url or (button.web_app.url if button.web_app else ""))
            external_checkout = url.hostname in {
                "web.tribute.tg", "gate.lava.top", "pay.fk.money", "auth.robokassa.ru", "pay.crypt.bot",
            } or "/freekassa/checkout" in url.path
            if target is not None or external_checkout:
                redirected = True
                buttons.append(InlineKeyboardButton(text=button.text, url=web_payment_url(*(target or ("", "")))))
            else:
                buttons.append(button)
        rows.append(buttons)
    has_stars = any((button.callback_data or '').startswith(('buy_stars_', 'menu_stars')) for row in rows for button in row)
    if redirected and config.TELEGRAM_STARS_ENABLED and not has_stars:
        rows.append([InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="menu_stars")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


class TelegramPaymentRequestMiddleware(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        if method.__api_method__ in {"sendInvoice", "createInvoiceLink"} and method.currency != "XTR":
            raise ValueError("Telegram native payments require XTR")
        markup = getattr(method, "reply_markup", None)
        if isinstance(markup, InlineKeyboardMarkup):
            method = method.model_copy(update={"reply_markup": website_payment_markup(markup)})
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
