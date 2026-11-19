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
        deep_link = isinstance(event, types.Message) and bool(event.text) and event.text.split()[0].split('@')[0] in {"/balance", "/wallet", "/topup", "/pay"}
        if isinstance(event, types.Message) and event.text and event.text.startswith("/start "):
            argument = event.text.split(maxsplit=1)[1]
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
