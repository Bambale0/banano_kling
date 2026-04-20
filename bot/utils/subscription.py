from aiogram import Bot

from bot.config import config


async def is_user_subscribed(bot: Bot, user_id: int) -> bool:
    """Проверяет подписку пользователя на канал."""
    try:
        member = await bot.get_chat_member(config.CHANNEL_USERNAME, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception:
        return False
