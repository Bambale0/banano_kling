"""Упрощённый стартовый обработчик - все через inline кнопки"""
from aiogram import Router
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart

from bot.keyboards import main_menu

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Приветственное сообщение с упрощённым меню"""
    await message.answer(
        "👋 <b>Привет!</b> Я бот для генерации изображений и видео.\n\n"
        "🎨 <b>Генерация изображения</b> — создать картинку по описанию\n"
        "✏️ <b>Редактировать изображение</b> — изменить загруженное фото\n"
        "🎬 <b>Генерация видео</b> — создать видео по описанию\n"
        "⚙️ <b>Настройки</b> — выбрать модель ИИ и качество\n\n"
        "Всё просто: выбирайте действие и следуйте подсказкам! 👇",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# Обработчики inline кнопок главного меню
@router.callback_query()
async def handle_main_menu(callback: CallbackQuery):
    """Обработка нажатий на кнопки главного меню"""
    data = callback.data
    
    if data == "menu_image_gen":
        await callback.answer()
        await callback.message.delete()
        from bot.handlers.image_generation import start_image_generation
        from aiogram.fsm.context import FSMContext
        state = FSMContext(
            bot=callback.bot,
            chat=callback.message.chat,
            user=callback.from_user,
            data={}
        )
        await start_image_generation(callback.message, state)
        
    elif data == "menu_image_edit":
        await callback.answer()
        await callback.message.delete()
        from bot.handlers.image_editing import start_image_editing
        from aiogram.fsm.context import FSMContext
        state = FSMContext(
            bot=callback.bot,
            chat=callback.message.chat,
            user=callback.from_user,
            data={}
        )
        await start_image_editing(callback.message, state)
        
    elif data == "menu_video_gen":
        await callback.answer()
        await callback.message.delete()
        from bot.handlers.video_generation import start_video_generation
        from aiogram.fsm.context import FSMContext
        state = FSMContext(
            bot=callback.bot,
            chat=callback.message.chat,
            user=callback.from_user,
            data={}
        )
        await start_video_generation(callback.message, state)
        
    elif data == "menu_settings":
        await callback.answer()
        await callback.message.delete()
        from bot.handlers.settings import show_settings
        await show_settings(callback.message)
        
    else:
        await callback.answer()
