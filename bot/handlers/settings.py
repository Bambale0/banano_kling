"""Обработчик настроек пользователя"""
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.services.user_settings import settings_manager
from bot.keyboards import main_menu

router = Router()
logger = logging.getLogger(__name__)


def settings_menu():
    """Меню настроек"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🤖 Модель изображений", callback_data="setting_image_model")
    builder.button(text="🎬 Модель видео (Kling)", callback_data="setting_kling_model")
    builder.button(text="🔙 Назад", callback_data="back_to_main")
    return builder.as_markup()


def image_model_selection(current_model: str = "flash"):
    """Выбор модели для генерации изображений"""
    flash_check = "✅ " if current_model == "flash" else ""
    pro_check = "✅ " if current_model == "pro" else ""
    
    builder = InlineKeyboardBuilder()
    builder.button(text=f"{flash_check}⚡ Flash (быстро)", callback_data="set_image_flash")
    builder.button(text=f"{pro_check}🎨 Pro (качество)", callback_data="set_image_pro")
    builder.button(text="🔙 Назад", callback_data="settings")
    return builder.as_markup()


def kling_model_selection(current_model: str = "std"):
    """Выбор модели Kling для генерации видео"""
    std_check = "✅ " if current_model == "std" else ""
    pro_check = "✅ " if current_model == "pro" else ""
    
    builder = InlineKeyboardBuilder()
    builder.button(text=f"{std_check}⚡ Kling Standard", callback_data="set_kling_std")
    builder.button(text=f"{pro_check}🎬 Kling Pro", callback_data="set_kling_pro")
    builder.button(text="🔙 Назад", callback_data="settings")
    return builder.as_markup()


# Обработчик inline кнопки "Настройки"
@router.callback_query(F.data == "menu_settings")
async def settings_callback(callback: CallbackQuery):
    """Настройки из главного меню"""
    await callback.answer()
    await callback.message.delete()
    await show_settings(callback.message)


@router.message(F.text == "⚙️ Настройки")
async def show_settings(message: Message):
    """Показывает настройки"""
    settings = settings_manager.get_settings(message.from_user.id)
    
    # Модель изображений
    if settings.image_model == "flash":
        image_model_name = "⚡ Flash"
    else:
        image_model_name = "🎨 Pro"
    
    # Модель видео (Kling)
    if settings.video_quality == "std":
        kling_model_name = "⚡ Kling Standard"
    else:
        kling_model_name = "🎬 Kling Pro"
    
    await message.answer(
        f"⚙️ <b>Ваши настройки</b>\n\n"
        f"🤖 <b>Модель изображений:</b> {image_model_name}\n"
        f"   Flash — быстро, Pro — качество\n\n"
        f"🎬 <b>Модель видео (Kling):</b> {kling_model_name}\n"
        f"   Standard — быстро, Pro — кинематографическое качество\n\n"
        f"<i>Нажмите, чтобы изменить:</i>",
        parse_mode="HTML",
        reply_markup=settings_menu()
    )


@router.callback_query(F.data == "settings")
async def back_to_settings(callback: CallbackQuery):
    """Возврат в настройки"""
    settings = settings_manager.get_settings(callback.from_user.id)
    
    if settings.image_model == "flash":
        image_model_name = "⚡ Flash"
    else:
        image_model_name = "🎨 Pro"
    
    if settings.video_quality == "std":
        kling_model_name = "⚡ Kling Standard"
    else:
        kling_model_name = "🎬 Kling Pro"
    
    await callback.message.edit_text(
        f"⚙️ <b>Ваши настройки</b>\n\n"
        f"🤖 <b>Модель изображений:</b> {image_model_name}\n"
        f"   Flash — быстро, Pro — качество\n\n"
        f"🎬 <b>Модель видео (Kling):</b> {kling_model_name}\n"
        f"   Standard — быстро, Pro — кинематографическое качество\n\n"
        f"<i>Нажмите, чтобы изменить:</i>",
        parse_mode="HTML",
        reply_markup=settings_menu()
    )


@router.callback_query(F.data == "setting_image_model")
async def select_image_model(callback: CallbackQuery):
    """Выбор модели изображений"""
    current = settings_manager.get_image_model(callback.from_user.id)
    await callback.message.edit_text(
        "🤖 <b>Выбор модели изображений</b>\n\n"
        "⚡ <b>Flash</b> — быстрая генерация, хорошее качество\n"
        "🎨 <b>Pro</b> — высочайшее качество, 4K, детализация\n\n"
        "<i>Выберите модель:</i>",
        parse_mode="HTML",
        reply_markup=image_model_selection(current)
    )


@router.callback_query(F.data.startswith("set_image_"))
async def set_image_model(callback: CallbackQuery):
    """Устанавливаем модель изображений"""
    model = callback.data.replace("set_image_", "")
    settings_manager.update_settings(callback.from_user.id, image_model=model)
    
    model_name = "⚡ Flash" if model == "flash" else "🎨 Pro"
    await callback.answer(f"Установлена модель: {model_name}")
    
    await back_to_settings(callback)


@router.callback_query(F.data == "setting_kling_model")
async def select_kling_model(callback: CallbackQuery):
    """Выбор модели Kling для видео"""
    current = settings_manager.get_video_quality(callback.from_user.id)
    await callback.message.edit_text(
        "🎬 <b>Выбор модели Kling для видео</b>\n\n"
        "⚡ <b>Kling Standard</b> — быстрая генерация\n"
        "🎬 <b>Kling Pro</b> — кинематографическое качество\n\n"
        "<i>Выберите модель:</i>",
        parse_mode="HTML",
        reply_markup=kling_model_selection(current)
    )


@router.callback_query(F.data.startswith("set_kling_"))
async def set_kling_model(callback: CallbackQuery):
    """Устанавливаем модель Kling"""
    quality = callback.data.replace("set_kling_", "")
    settings_manager.update_settings(callback.from_user.id, video_quality=quality)
    
    quality_name = "⚡ Kling Standard" if quality == "std" else "🎬 Kling Pro"
    await callback.answer(f"Установлена модель: {quality_name}")
    
    await back_to_settings(callback)


@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    """Возврат в главное меню - показываем меню без удаления стартового сообщения"""
    # Просто показываем меню, не удаляя старое сообщение
    await callback.message.answer(
        "👋 <b>Привет!</b> Я бот для генерации изображений и видео.\n\n"
        "🎨 <b>Генерация изображения</b> — создать картинку по описанию\n"
        "✏️ <b>Редактировать изображение</b> — изменить загруженное фото\n"
        "🎬 <b>Генерация видео</b> — создать видео по описанию\n"
        "⚙️ <b>Настройки</b> — выбрать модель ИИ и качество\n\n"
        "Всё просто: выбирайте действие и следуйте подсказкам! 👇",
        parse_mode="HTML",
        reply_markup=main_menu()
    )
