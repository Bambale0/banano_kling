"""Telegram entry to the same authenticated full Genjutsu studio."""
from aiogram import Router, types
from aiogram.filters import Command

from bot.config import config
from bot.genjutsu.runtime import studio_url

router = Router(name='genjutsu')


@router.message(Command('genjutsu'))
async def open_genjutsu(message: types.Message) -> None:
    if message.chat.type != 'private':
        await message.answer('Откройте личный чат с ботом, чтобы работать с Genjutsu.')
        return
    await message.answer(
        'Higgsfield Genjutsu\n\nПеренос движения, замена персонажей и предметов, стилизация видео. '
        'Исходники, настройки, стоимость и результаты доступны в студии. '
        'Закрытие окна не прерывает принятую генерацию.',
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[
            types.InlineKeyboardButton(text='Открыть Genjutsu',
                web_app=types.WebAppInfo(url=studio_url(config.mini_app_url))),
        ]]),
    )
