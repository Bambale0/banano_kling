"""Упрощённое редактирование изображений"""
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.types import InputFile

from bot.services.gemini_service import gemini_service
from bot.services.user_settings import settings_manager
from bot.keyboards import aspect_ratio_keyboard, main_menu
from bot.states import ImageEditState

router = Router()
logger = logging.getLogger(__name__)


# Обработчик inline кнопки "Редактировать изображение"
@router.callback_query(F.data == "menu_image_edit")
async def start_image_editing_callback(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования из главного меню"""
    await callback.answer()
    await callback.message.delete()
    await start_image_editing(callback.message, state)


async def start_image_editing(message: Message, state: FSMContext):
    """Начало редактирования - просим загрузить изображение"""
    await message.answer(
        "✏️ <b>Редактирование изображения</b>\n\n"
        "📎 <b>Загрузите изображение</b> (фото или файл)\n"
        "Поддерживаются JPG, PNG",
        parse_mode="HTML"
    )
    await state.set_state(ImageEditState.waiting_for_image)


@router.message(ImageEditState.waiting_for_image, F.photo)
async def receive_photo(message: Message, state: FSMContext):
    """Получили фото"""
    photo = message.photo[-1]
    await process_image(message, photo.file_id, state)


@router.message(ImageEditState.waiting_for_image, F.document)
async def receive_document(message: Message, state: FSMContext):
    """Получили файл"""
    doc = message.document
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        await message.answer("❌ Пожалуйста, отправьте изображение (JPG или PNG)")
        return
    await process_image(message, doc.file_id, state)


async def process_image(message: Message, file_id: str, state: FSMContext):
    """Обработка полученного изображения"""
    await message.answer("⏳ Загружаю изображение...")
    
    try:
        file = await message.bot.get_file(file_id)
        image_bytes = await message.bot.download_file(file.file_path)
        image_data = image_bytes.read()
        
        await state.update_data(image=image_data)
        
        await message.answer(
            "✅ Изображение загружено!\n\n"
            "✏️ <b>Что нужно изменить?</b>\n"
            "Например:\n"
            "• «Сделай фон синим»\n"
            "• «Добавь солнечные очки»\n"
            "• «Преврати в мультфильм»",
            parse_mode="HTML"
        )
        await state.set_state(ImageEditState.waiting_for_prompt)
        
    except Exception as e:
        logger.exception(f"Failed to process image: {e}")
        await message.answer("❌ Ошибка загрузки изображения. Попробуйте другое.")


@router.message(ImageEditState.waiting_for_prompt)
async def receive_edit_prompt(message: Message, state: FSMContext):
    """Получили промпт для редактирования - просим выбрать формат"""
    prompt = message.text.strip()
    
    if len(prompt) < 3:
        await message.answer("❌ Описание слишком короткое. Напишите подробнее:")
        return
    
    await state.update_data(prompt=prompt)
    
    await message.answer(
        f"✅ Задача: <i>{prompt}</i>\n\n"
        f"📐 <b>Выберите формат результата:</b>",
        parse_mode="HTML",
        reply_markup=aspect_ratio_keyboard()
    )
    await state.set_state(ImageEditState.waiting_for_aspect_ratio)


@router.callback_query(ImageEditState.waiting_for_aspect_ratio, F.data.startswith("aspect_"))
async def execute_edit(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Выполняем редактирование"""
    aspect_ratio = callback.data.replace("aspect_", "")
    data = await state.get_data()
    prompt = data["prompt"]
    image_data = data["image"]
    user_id = callback.from_user.id
    
    # Получаем модель из настроек
    model_pref = settings_manager.get_image_model(user_id)
    model = "gemini-2.5-flash-image" if model_pref == "flash" else "gemini-3-pro-image-preview"
    
    await callback.message.edit_text("⏳ Редактирую изображение...")
    await state.set_state(ImageEditState.generating)
    
    try:
        result = await gemini_service.edit_image(
            image_bytes=image_data,
            instruction=prompt,
            model=model,
            aspect_ratio=aspect_ratio
        )
        
        if result:
            await callback.message.delete()
            # Сохраняем во временный файл и отправляем
            import tempfile
            import os
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                f.write(result)
                temp_path = f.name
            try:
                await bot.send_photo(
                    chat_id=user_id,
                    photo=InputFile(temp_path),
                    caption=f"✅ Готово!\n📝 {prompt}\n📐 {aspect_ratio}",
                    reply_markup=main_menu()
                )
            finally:
                os.unlink(temp_path)
        else:
            await callback.message.edit_text(
                "❌ Не удалось отредактировать. Попробуйте другой запрос.",
                reply_markup=main_menu()
            )
            
    except Exception as e:
        logger.exception(f"Image editing failed: {e}")
        await callback.message.edit_text(
            "❌ Ошибка редактирования. Попробуйте позже.",
            reply_markup=main_menu()
        )
    
    await state.clear()
