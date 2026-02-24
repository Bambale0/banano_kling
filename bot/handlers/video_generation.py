"""Упрощённая генерация видео"""
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.services.kling_service import kling_service
from bot.services.user_settings import settings_manager
from bot.keyboards import video_aspect_ratio_keyboard, video_duration_keyboard, main_menu
from bot.states import VideoGenState

router = Router()
logger = logging.getLogger(__name__)


# Обработчик inline кнопки "Генерация видео"
@router.callback_query(F.data == "menu_video_gen")
async def start_video_generation_callback(callback: CallbackQuery, state: FSMContext):
    """Начало генерации видео из главного меню"""
    await callback.answer()
    await callback.message.delete()
    await start_video_generation(callback.message, state)


async def start_video_generation(message: Message, state: FSMContext):
    """Начало генерации видео"""
    quality = settings_manager.get_video_quality(message.from_user.id)
    quality_name = "⚡ Standard" if quality == "std" else "🎬 Pro"
    
    await message.answer(
        f"🎬 <b>Генерация видео</b>\n"
        f"Качество: {quality_name}\n\n"
        f"✏️ <b>Опишите видео:</b>\n"
        f"Например: «Кот танцует под дождём»",
        parse_mode="HTML"
    )
    await state.set_state(VideoGenState.waiting_for_prompt)


@router.message(VideoGenState.waiting_for_prompt)
async def receive_video_prompt(message: Message, state: FSMContext):
    """Получили промпт"""
    prompt = message.text.strip()
    
    if len(prompt) < 3:
        await message.answer("❌ Описание слишком короткое:")
        return
    
    await state.update_data(prompt=prompt)
    
    await message.answer(
        f"✅ {prompt}\n\n"
        f"📐 <b>Выберите формат видео:</b>",
        parse_mode="HTML",
        reply_markup=video_aspect_ratio_keyboard()
    )
    await state.set_state(VideoGenState.waiting_for_aspect_ratio)


@router.callback_query(VideoGenState.waiting_for_aspect_ratio, F.data.startswith("video_aspect_"))
async def receive_video_aspect(callback: CallbackQuery, state: FSMContext):
    aspect_ratio = callback.data.replace("video_aspect_", "")
    await state.update_data(aspect_ratio=aspect_ratio)
    
    await callback.message.edit_text(
        f"📐 {aspect_ratio}\n\n"
        f"⏱ <b>Выберите длительность:</b>",
        parse_mode="HTML",
        reply_markup=video_duration_keyboard()
    )
    await state.set_state(VideoGenState.waiting_for_duration)


@router.callback_query(VideoGenState.waiting_for_duration, F.data.startswith("duration_"))
async def generate_video(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Запускаем генерацию видео"""
    duration = int(callback.data.replace("duration_", ""))
    data = await state.get_data()
    prompt = data["prompt"]
    aspect_ratio = data["aspect_ratio"]
    user_id = callback.from_user.id
    
    quality = settings_manager.get_video_quality(user_id)
    
    await callback.message.edit_text(
        f"⏳ Создаю видео...\n"
        f"Это может занять 2-5 минут"
    )
    await state.set_state(VideoGenState.generating)
    
    try:
        if quality == "pro":
            result = await kling_service.generate_video_pro(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio
            )
        else:
            result = await kling_service.generate_video_std(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio
            )
        
        if result and result.get("task_id"):
            task_id = result["task_id"]
            
            # Ждём завершения (с таймаутом)
            status = await kling_service.wait_for_completion(task_id, max_attempts=60, delay=5)
            
            if status and status.get("data", {}).get("status") == "COMPLETED":
                video_url = status["data"]["result"]["video_url"]
                
                await callback.message.delete()
                await bot.send_video(
                    chat_id=user_id,
                    video=video_url,
                    caption=f"✅ Готово!\n📝 {prompt}\n📐 {aspect_ratio} | ⏱ {duration}сек",
                    reply_markup=main_menu()
                )
            else:
                await callback.message.edit_text(
                    "❌ Видео не удалось создать. Попробуйте другой запрос.",
                    reply_markup=main_menu()
                )
        else:
            await callback.message.edit_text(
                "❌ Ошибка запуска генерации.",
                reply_markup=main_menu()
            )
            
    except Exception as e:
        logger.exception(f"Video generation failed: {e}")
        await callback.message.edit_text(
            "❌ Ошибка генерации видео.",
            reply_markup=main_menu()
        )
    
    await state.clear()
