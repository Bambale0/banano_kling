"""Native Stars entry and settlement routing, without website handoffs."""
from aiogram import BaseMiddleware, types
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import config
from bot.payment_utils import package_stars_amount
from bot.services.preset_manager import preset_manager


class TelegramPaymentSurfaceMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        # Financial service updates must always reach the idempotent settlement
        # handler, regardless of a user's stale conversation state.
        if isinstance(event, types.Message) and event.successful_payment:
            return await handler(event, data)
        if isinstance(event, types.CallbackQuery) and event.data == "menu_stars":
            rows = []
            if config.TELEGRAM_STARS_ENABLED:
                for package in preset_manager.get_packages():
                    rows.append([InlineKeyboardButton(
                        text=f"{package['name']} · {package_stars_amount(package)}⭐",
                        callback_data=f"buy_stars_{package['id']}",
                    )])
            rows.append([InlineKeyboardButton(text="Другие способы оплаты", callback_data="menu_balance")])
            await event.answer()
            if event.message:
                await event.message.answer("⭐ Выберите пакет Stars" if config.TELEGRAM_STARS_ENABLED else "Stars временно недоступны.", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
            return
        return await handler(event, data)


class TelegramPaymentRequestMiddleware(BaseRequestMiddleware):
    def __init__(self):
        self.fsm = None

    async def __call__(self, make_request, bot, method):
        if method.__api_method__ in {"sendInvoice", "createInvoiceLink"} and method.currency != "XTR":
            raise ValueError("Telegram native payments require XTR")
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
