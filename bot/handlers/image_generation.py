"""Упрощённая генерация изображений"""
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.types import InputFile

from bot.services.gemini_service import gemini_service
from bot.services.user_settings import settings_manager
from bot.keyboards import aspect_ratio_keyboard, main_menu
from bot.states import ImageGenState

router = Router()
logger = logging.getLogger(__name__)


# Обработчик inline кнопки "Генерация изображения"
@router.callback_query(F.data == "menu_image_gen")
async def start_image_generation_callback(callback: CallbackQuery, state: FSMContext):
    """Начало генерации из главного меню"""
    await callback.answer()
    await callback.message.delete()
    await start_image_generation(callback.message, state)


async def start_image_generation(message: Message, state: FSMContext):
    """Начало генерации - сразу просим промпт"""
    model = settings_manager.get_image_model(message.from_user.id)
    model_name = "⚡ Flash" if model == "flash" else "🎨 Pro"
    
    await message.answer(
        f"🎨 <b>Генерация изображения</b>\n"
        f"Модель: {model_name}\n\n"
        f"✏️ <b>Введите описание изображения:</b>\n"
        f"Например: «Красный кот в космосе»",
        parse_mode="HTML"
    )
    await state.set_state(ImageGenState.waiting_for_prompt)


@router.message(ImageGenState.waiting_for_prompt)
async def receive_prompt(message: Message, state: FSMContext):
    """Получили промпт - сразу показываем аспект-ратио"""
    prompt = message.text.strip()
    
    if len(prompt) < 3:
        await message.answer("❌ Описание слишком короткое. Попробуйте подробнее:")
        return
    
    await state.update_data(prompt=prompt)
    
    await message.answer(
        f"✅ Описание принято: <i>{prompt}</i>\n\n"
        f"📐 <b>Выберите формат изображения:</b>",
        parse_mode="HTML",
        reply_markup=aspect_ratio_keyboard()
    )
    await state.set_state(ImageGenState.waiting_for_aspect_ratio)


@router.callback_query(ImageGenState.waiting_for_aspect_ratio, F.data.startswith("aspect_"))
async def receive_aspect_ratio(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Получили аспект-ратио - сразу генерируем"""
    aspect_ratio = callback.data.replace("aspect_", "")
    data = await state.get_data()
    prompt = data["prompt"]
    user_id = callback.from_user.id
    
    # Определяем модель
    model_pref = settings_manager.get_image_model(user_id)
    model = "gemini-2.5-flash-image" if model_pref == "flash" else "gemini-3-pro-image-preview"
    
    await callback.message.edit_text("⏳ Генерирую изображение...")
    await state.set_state(ImageGenState.generating)
    
    try:
        result = await gemini_service.generate_image(
            prompt=prompt,
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
                "❌ Не удалось сгенерировать изображение. Попробуйте другой запрос.",
                reply_markup=main_menu()
            )
            
    except Exception as e:
        logger.exception(f"Image generation failed: {e}")
        await callback.message.edit_text(
            "❌ Ошибка генерации. Попробуйте позже.",
            reply_markup=main_menu()
        )
    
    await state.clear()


@router.callback_query(F.data == "cancel")
async def cancel_generation(callback: CallbackQuery, state: FSMContext):
    """Отмена"""
    await callback.message.edit_text("❌ Отменено")
    await callback.message.answer("Главное меню:", reply_markup=main_menu())
    await state.clear()
