from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.utils.subscription import is_user_subscribed


class SubscriptionCheckMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        bot = data.get("bot")
        if not bot:
            return await handler(event, data)

        user = event.from_user
        if config.is_admin(user.id):
            return await handler(event, data)

        # Пропускаем /start
        if (
            isinstance(event, Message)
            and event.text
            and event.text.startswith("/start")
        ):
            return await handler(event, data)

        subscribed = True  # ВРЕМЕННО ОТКЛЮЧЕНА ПРОВЕРКА ПОДПИСКИ НА КАНАЛ
        if not subscribed:
            builder = InlineKeyboardBuilder()
            builder.button(text="🔗 Подписаться на канал", url="https://t.me/FS_2Loop")
            builder.button(
                text="Проверить подписку", callback_data="check_subscription"
            )
            kb = builder.as_markup()

            text = "❌ Чтобы использовать бота, <b>подпишитесь на канал</b> <code>@FS_2Loop</code>\\n\\nПосле подписки нажмите кнопку ниже или /start"
            if isinstance(event, Message):
                await event.answer(text, reply_markup=kb, parse_mode="HTML")
            elif isinstance(event, CallbackQuery):
                try:
                    await event.message.edit_text(
                        text, reply_markup=kb, parse_mode="HTML"
                    )
                except:
                    await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
            return

        return await handler(event, data)
