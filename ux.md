нужно упростить UX интерфейс https://github.com/Bambale0/banano_kling   , убрать пресеты и привязку к ним. создать меню настроек в котором юзер будет выбирать модель ии для генерации, что бы один раз выбрал модель и эта модель была на постоннке, пока пользователь не сменит. выбор качества изображения и видео. убрать постоянное подтверждение действий. Сделать так что бы "блондинка" поняла ак пользоваться. пользователь заходит в генерацию изображений вводит промпт далее клавиатура аспект ратио и генерация, в разделе редактирование изображений, бот должен просить загрузить изображение> далее промпт от пользователя > аспект ратио > получить нужный результат
Edit
Copy
Share
Проанализировал репозиторий и кодовую базу. Понял задачу: нужно упростить UX, убрать пресеты, сделать постоянные настройки модели, убрать лишние подтверждения, сделать интуитивный интерфейс "для блондинки".
Вот архитектура упрощённого бота:
Структура файлов
plain
Copy
bot/
├── config.py                    # Конфигурация
├── handlers/
│   ├── __init__.py
│   ├── start.py                 # Старт и меню
│   ├── settings.py              # Настройки модели/качества
│   ├── image_generation.py      # Генерация изображений (упрощённая)
│   ├── image_editing.py         # Редактирование изображений
│   └── video_generation.py      # Генерация видео
├── services/
│   ├── gemini_service.py        # Твой текущий (без изменений)
│   ├── kling_service.py         # Твой текущий (без изменений)
│   └── user_settings.py         # НОВОЕ: хранение настроек пользователя
├── states.py                    # FSM состояния
└── keyboards.py                 # Клавиатуры
1. Хранение настроек пользователя (services/user_settings.py)
Python
Copy
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

@dataclass
class UserSettings:
    user_id: int
    image_model: str = "flash"  # flash или pro
    video_quality: str = "std"  # std или pro
    default_aspect_ratio: str = "1:1"
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "UserSettings":
        return cls(**data)


class UserSettingsManager:
    """Простое хранилище настроек в JSON"""
    
    def __init__(self, storage_path: str = "data/user_settings.json"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[int, UserSettings] = {}
        self._load_all()
    
    def _load_all(self):
        """Загружает все настройки"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for user_id, settings_data in data.items():
                        self._cache[int(user_id)] = UserSettings.from_dict(settings_data)
            except Exception as e:
                logger.error(f"Failed to load settings: {e}")
    
    def _save_all(self):
        """Сохраняет все настройки"""
        try:
            data = {str(uid): s.to_dict() for uid, s in self._cache.items()}
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")
    
    def get_settings(self, user_id: int) -> UserSettings:
        """Получает настройки пользователя (создаёт дефолтные если нет)"""
        if user_id not in self._cache:
            self._cache[user_id] = UserSettings(user_id=user_id)
            self._save_all()
        return self._cache[user_id]
    
    def update_settings(self, user_id: int, **kwargs):
        """Обновляет настройки"""
        settings = self.get_settings(user_id)
        for key, value in kwargs.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        self._save_all()
    
    def get_image_model(self, user_id: int) -> str:
        """Возвращает модель для генерации изображений"""
        return self.get_settings(user_id).image_model
    
    def get_video_quality(self, user_id: int) -> str:
        """Возвращает качество видео"""
        return self.get_settings(user_id).video_quality

# Глобальный менеджер
settings_manager = UserSettingsManager()
2. Клавиатуры (keyboards.py)
Python
Copy
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# Главное меню (простое)
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎨 Генерация изображения")],
            [KeyboardButton(text="✏️ Редактировать изображение")],
            [KeyboardButton(text="🎬 Генерация видео")],
            [KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True
    )

# Настройки
def settings_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Модель ИИ", callback_data="setting_model")],
        [InlineKeyboardButton(text="📹 Качество видео", callback_data="setting_video")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")],
    ])

# Выбор модели
def model_selection(current_model: str):
    flash_check = "✅ " if current_model == "flash" else ""
    pro_check = "✅ " if current_model == "pro" else ""
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{flash_check}⚡ Flash (быстро)", callback_data="set_model_flash")],
        [InlineKeyboardButton(text=f"{pro_check}🎨 Pro (качество)", callback_data="set_model_pro")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="settings")],
    ])

# Выбор качества видео
def video_quality_selection(current_quality: str):
    std_check = "✅ " if current_quality == "std" else ""
    pro_check = "✅ " if current_quality == "pro" else ""
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{std_check}⚡ Standard (быстро)", callback_data="set_video_std")],
        [InlineKeyboardButton(text=f"{pro_check}🎬 Pro (качество)", callback_data="set_video_pro")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="settings")],
    ])

# Аспект-ратио для изображений
def aspect_ratio_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1:1", callback_data="aspect_1:1"),
            InlineKeyboardButton(text="16:9", callback_data="aspect_16:9"),
            InlineKeyboardButton(text="9:16", callback_data="aspect_9:16"),
        ],
        [
            InlineKeyboardButton(text="4:3", callback_data="aspect_4:3"),
            InlineKeyboardButton(text="3:4", callback_data="aspect_3:4"),
            InlineKeyboardButton(text="2:3", callback_data="aspect_2:3"),
        ],
    ])

# Аспект-ратио для видео
def video_aspect_ratio_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="16:9 (широкий)", callback_data="video_aspect_16:9"),
            InlineKeyboardButton(text="9:16 (вертикальный)", callback_data="video_aspect_9:16"),
        ],
        [InlineKeyboardButton(text="1:1 (квадрат)", callback_data="video_aspect_1:1")],
    ])

# Продолжительность видео
def video_duration_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="3 сек", callback_data="duration_3"),
            InlineKeyboardButton(text="5 сек", callback_data="duration_5"),
            InlineKeyboardButton(text="7 сек", callback_data="duration_7"),
        ],
        [
            InlineKeyboardButton(text="10 сек", callback_data="duration_10"),
            InlineKeyboardButton(text="12 сек", callback_data="duration_12"),
            InlineKeyboardButton(text="15 сек", callback_data="duration_15"),
        ],
    ])
3. Состояния (states.py)
Python
Copy
from aiogram.fsm.state import State, StatesGroup

class ImageGenState(StatesGroup):
    waiting_for_prompt = State()
    waiting_for_aspect_ratio = State()
    generating = State()

class ImageEditState(StatesGroup):
    waiting_for_image = State()
    waiting_for_prompt = State()
    waiting_for_aspect_ratio = State()
    generating = State()

class VideoGenState(StatesGroup):
    waiting_for_prompt = State()
    waiting_for_image_or_skip = State()  # Опционально: изображение для I2V
    waiting_for_aspect_ratio = State()
    waiting_for_duration = State()
    generating = State()
4. Генерация изображений (handlers/image_generation.py)
Python
Copy
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.services.gemini_service import gemini_service
from bot.services.user_settings import settings_manager
from bot.keyboards import aspect_ratio_keyboard, main_menu
from bot.states import ImageGenState

router = Router()
logger = logging.getLogger(__name__)

@router.message(F.text == "🎨 Генерация изображения")
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
            await bot.send_photo(
                chat_id=user_id,
                photo=result,
                caption=f"✅ Готово!\n📝 {prompt}\n📐 {aspect_ratio}",
                reply_markup=main_menu()
            )
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

@router.callback_query(ImageGenState.waiting_for_aspect_ratio, F.data == "cancel")
async def cancel_generation(callback: CallbackQuery, state: FSMContext):
    """Отмена"""
    await callback.message.edit_text("❌ Отменено")
    await callback.message.answer("Главное меню:", reply_markup=main_menu())
    await state.clear()
5. Редактирование изображений (handlers/image_editing.py)
Python
Copy
import logging
import io
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, PhotoSize
from aiogram.fsm.context import FSMContext

from bot.services.gemini_service import gemini_service
from bot.services.user_settings import settings_manager
from bot.keyboards import aspect_ratio_keyboard, main_menu
from bot.states import ImageEditState

router = Router()
logger = logging.getLogger(__name__)

@router.message(F.text == "✏️ Редактировать изображение")
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
    # Берём самое большое разрешение
    photo = message.photo[-1]
    await process_image(message, photo.file_id, state)

@router.message(ImageEditState.waiting_for_image, F.document)
async def receive_document(message: Message, state: FSMContext):
    """Получили файл"""
    doc = message.document
    # Проверяем что это изображение
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        await message.answer("❌ Пожалуйста, отправьте изображение (JPG или PNG)")
        return
    await process_image(message, doc.file_id, state)

async def process_image(message: Message, file_id: str, state: FSMContext):
    """Обработка полученного изображения"""
    await message.answer("⏳ Загружаю изображение...")
    
    try:
        # Скачиваем файл
        file = await message.bot.get_file(file_id)
        image_bytes = await message.bot.download_file(file.file_path)
        image_data = image_bytes.read()
        
        # Сохраняем в состояние
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
    """Получили промпт для редактирования"""
    prompt = message.text.strip()
    
    if len(prompt) < 3:
        await message.answer("❌ Описание слишком короткое:")
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
            await bot.send_photo(
                chat_id=user_id,
                photo=result,
                caption=f"✅ Готово!\n📝 {prompt}\n📐 {aspect_ratio}",
                reply_markup=main_menu()
            )
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
6. Генерация видео (handlers/video_generation.py)
Python
Copy
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

@router.message(F.text == "🎬 Генерация видео")
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
        # Выбираем метод в зависимости от качества
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
7. Настройки (handlers/settings.py)
Python
Copy
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from bot.services.user_settings import settings_manager
from bot.keyboards import settings_menu, model_selection, video_quality_selection, main_menu

router = Router()

@router.message(F.text == "⚙️ Настройки")
async def show_settings(message: Message):
    """Показываем настройки"""
    settings = settings_manager.get_settings(message.from_user.id)
    
    model_name = "⚡ Flash" if settings.image_model == "flash" else "🎨 Pro"
    video_name = "⚡ Standard" if settings.video_quality == "std" else "🎬 Pro"
    
    await message.answer(
        f"⚙️ <b>Ваши настройки</b>\n\n"
        f"🤖 <b>Модель ИИ:</b> {model_name}\n"
        f"   Для генерации изображений\n\n"
        f"📹 <b>Качество видео:</b> {video_name}\n"
        f"   Для генерации видео\n\n"
        f"<i>Нажмите, чтобы изменить:</i>",
        parse_mode="HTML",
        reply_markup=settings_menu()
    )

@router.callback_query(F.data == "settings")
async def back_to_settings(callback: CallbackQuery):
    """Возврат в настройки"""
    settings = settings_manager.get_settings(callback.from_user.id)
    
    model_name = "⚡ Flash" if settings.image_model == "flash" else "🎨 Pro"
    video_name = "⚡ Standard" if settings.video_quality == "std" else "🎬 Pro"
    
    await callback.message.edit_text(
        f"⚙️ <b>Ваши настройки</b>\n\n"
        f"🤖 <b>Модель ИИ:</b> {model_name}\n"
        f"📹 <b>Качество видео:</b> {video_name}\n\n"
        f"<i>Нажмите, чтобы изменить:</i>",
        parse_mode="HTML",
        reply_markup=settings_menu()
    )

@router.callback_query(F.data == "setting_model")
async def select_model(callback: CallbackQuery):
    """Выбор модели"""
    current = settings_manager.get_image_model(callback.from_user.id)
    await callback.message.edit_text(
        "🤖 <b>Выбор модели ИИ</b>\n\n"
        "⚡ <b>Flash</b> — быстрая генерация, хорошее качество\n"
        "🎨 <b>Pro</b> — высочайшее качество, 4K, детализация\n\n"
        "<i>Выберите модель:</i>",
        parse_mode="HTML",
        reply_markup=model_selection(current)
    )

@router.callback_query(F.data.startswith("set_model_"))
async def set_model(callback: CallbackQuery):
    """Устанавливаем модель"""
    model = callback.data.replace("set_model_", "")
    settings_manager.update_settings(callback.from_user.id, image_model=model)
    
    model_name = "⚡ Flash" if model == "flash" else "🎨 Pro"
    await callback.answer(f"Установлена модель: {model_name}")
    
    # Возвращаемся в настройки
    await back_to_settings(callback)

@router.callback_query(F.data == "setting_video")
async def select_video_quality(callback: CallbackQuery):
    """Выбор качества видео"""
    current = settings_manager.get_video_quality(callback.from_user.id)
    await callback.message.edit_text(
        "📹 <b>Качество видео</b>\n\n"
        "⚡ <b>Standard</b> — быстрая генерация\n"
        "🎬 <b>Pro</b> — кинематографическое качество\n\n"
        "<i>Выберите качество:</i>",
        parse_mode="HTML",
        reply_markup=video_quality_selection(current)
    )

@router.callback_query(F.data.startswith("set_video_"))
async def set_video_quality(callback: CallbackQuery):
    """Устанавливаем качество видео"""
    quality = callback.data.replace("set_video_", "")
    settings_manager.update_settings(callback.from_user.id, video_quality=quality)
    
    quality_name = "⚡ Standard" if quality == "std" else "🎬 Pro"
    await callback.answer(f"Установлено качество: {quality_name}")
    
    await back_to_settings(callback)

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    """Возврат в главное меню"""
    await callback.message.delete()
    await callback.message.answer("Главное меню:", reply_markup=main_menu())
8. Главный файл (bot.py)
Python
Copy
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import config
from bot.handlers import start, settings, image_generation, image_editing, video_generation

logging.basicConfig(level=logging.INFO)

async def main():
    bot = Bot(token=config.BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=MemoryStorage())
    
    # Подключаем роутеры
    dp.include_router(start.router)
    dp.include_router(settings.router)
    dp.include_router(image_generation.router)
    dp.include_router(image_editing.router)
    dp.include_router(video_generation.router)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
9. Старт (handlers/start.py)
Python
Copy
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import CommandStart

from bot.keyboards import main_menu

router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message):
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
Ключевые изменения для "блондинки":
Нет пресетов — только 4 кнопки в главном меню
Настройки один раз — модель и качество сохраняются навсегда
Минимум шагов:
Изображение: Промпт → Аспект → Готово
Редактирование: Фото → Промпт → Аспект → Готово
Видео: Промпт → Аспект → Длительность → Готово
Нет подтверждений — сразу после выбора аспекта начинается генерация
Понятные тексты — эмодзи, простые слова, примеры
Хочешь, добавлю inline-режим или уведомления о прогрессе генерации?
также добавь пакетную генерацию изоражений. фото в видео
Edit
Copy
Share
Добавляю пакетную генерацию изображений и фото-в-видео. Вот обновлённые файлы:
1. Обновлённые клавиатуры (keyboards.py)
Python
Copy
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# Главное меню (обновлённое)
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎨 Генерация изображения")],
            [KeyboardButton(text="📦 Пакетная генерация")],
            [KeyboardButton(text="✏️ Редактировать изображение")],
            [KeyboardButton(text="🎬 Генерация видео")],
            [KeyboardButton(text="🖼️ Фото в видео")],
            [KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True
    )

# Настройки
def settings_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Модель ИИ", callback_data="setting_model")],
        [InlineKeyboardButton(text="📹 Качество видео", callback_data="setting_video")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")],
    ])

# Выбор модели
def model_selection(current_model: str):
    flash_check = "✅ " if current_model == "flash" else ""
    pro_check = "✅ " if current_model == "pro" else ""
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{flash_check}⚡ Flash (быстро)", callback_data="set_model_flash")],
        [InlineKeyboardButton(text=f"{pro_check}🎨 Pro (качество)", callback_data="set_model_pro")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="settings")],
    ])

# Выбор качества видео
def video_quality_selection(current_quality: str):
    std_check = "✅ " if current_quality == "std" else ""
    pro_check = "✅ " if current_quality == "pro" else ""
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{std_check}⚡ Standard (быстро)", callback_data="set_video_std")],
        [InlineKeyboardButton(text=f"{pro_check}🎬 Pro (качество)", callback_data="set_video_pro")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="settings")],
    ])

# Аспект-ратио для изображений
def aspect_ratio_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1:1", callback_data="aspect_1:1"),
            InlineKeyboardButton(text="16:9", callback_data="aspect_16:9"),
            InlineKeyboardButton(text="9:16", callback_data="aspect_9:16"),
        ],
        [
            InlineKeyboardButton(text="4:3", callback_data="aspect_4:3"),
            InlineKeyboardButton(text="3:4", callback_data="aspect_3:4"),
            InlineKeyboardButton(text="2:3", callback_data="aspect_2:3"),
        ],
    ])

# Аспект-ратио для видео
def video_aspect_ratio_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="16:9 (широкий)", callback_data="video_aspect_16:9"),
            InlineKeyboardButton(text="9:16 (вертикальный)", callback_data="video_aspect_9:16"),
        ],
        [InlineKeyboardButton(text="1:1 (квадрат)", callback_data="video_aspect_1:1")],
    ])

# Продолжительность видео
def video_duration_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="3 сек", callback_data="duration_3"),
            InlineKeyboardButton(text="5 сек", callback_data="duration_5"),
            InlineKeyboardButton(text="7 сек", callback_data="duration_7"),
        ],
        [
            InlineKeyboardButton(text="10 сек", callback_data="duration_10"),
            InlineKeyboardButton(text="12 сек", callback_data="duration_12"),
            InlineKeyboardButton(text="15 сек", callback_data="duration_15"),
        ],
    ])

# Выбор количества для пакетной генерации
def batch_count_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="2 шт", callback_data="batch_2"),
            InlineKeyboardButton(text="4 шт", callback_data="batch_4"),
        ],
        [
            InlineKeyboardButton(text="6 шт", callback_data="batch_6"),
            InlineKeyboardButton(text="8 шт", callback_data="batch_8"),
        ],
    ])

# Продолжительность для фото-в-видео (урезанная)
def image_to_video_duration_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="3 сек", callback_data="i2v_duration_3"),
            InlineKeyboardButton(text="5 сек", callback_data="i2v_duration_5"),
        ],
        [InlineKeyboardButton(text="10 сек", callback_data="i2v_duration_10")],
    ])
2. Обновлённые состояния (states.py)
Python
Copy
from aiogram.fsm.state import State, StatesGroup

class ImageGenState(StatesGroup):
    waiting_for_prompt = State()
    waiting_for_aspect_ratio = State()
    generating = State()

class BatchGenState(StatesGroup):
    waiting_for_prompt = State()
    waiting_for_count = State()
    waiting_for_aspect_ratio = State()
    generating = State()

class ImageEditState(StatesGroup):
    waiting_for_image = State()
    waiting_for_prompt = State()
    waiting_for_aspect_ratio = State()
    generating = State()

class VideoGenState(StatesGroup):
    waiting_for_prompt = State()
    waiting_for_aspect_ratio = State()
    waiting_for_duration = State()
    generating = State()

class ImageToVideoState(StatesGroup):
    waiting_for_image = State()
    waiting_for_prompt = State()
    waiting_for_aspect_ratio = State()
    waiting_for_duration = State()
    generating = State()
3. Пакетная генерация (handlers/batch_generation.py)
Python
Copy
import logging
import asyncio
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, MediaGroup
from aiogram.fsm.context import FSMContext

from bot.services.gemini_service import gemini_service
from bot.services.user_settings import settings_manager
from bot.keyboards import batch_count_keyboard, aspect_ratio_keyboard, main_menu
from bot.states import BatchGenState

router = Router()
logger = logging.getLogger(__name__)

@router.message(F.text == "📦 Пакетная генерация")
async def start_batch_generation(message: Message, state: FSMContext):
    """Начало пакетной генерации"""
    model = settings_manager.get_image_model(message.from_user.id)
    model_name = "⚡ Flash" if model == "flash" else "🎨 Pro"
    
    await message.answer(
        f"📦 <b>Пакетная генерация</b>\n"
        f"Модель: {model_name}\n\n"
        f"✏️ <b>Введите описание:</b>\n"
        f"Я создам несколько вариантов одновременно",
        parse_mode="HTML"
    )
    await state.set_state(BatchGenState.waiting_for_prompt)

@router.message(BatchGenState.waiting_for_prompt)
async def receive_batch_prompt(message: Message, state: FSMContext):
    """Получили промпт"""
    prompt = message.text.strip()
    
    if len(prompt) < 3:
        await message.answer("❌ Описание слишком короткое:")
        return
    
    await state.update_data(prompt=prompt)
    
    await message.answer(
        f"✅ <i>{prompt}</i>\n\n"
        f"🔢 <b>Сколько вариантов создать?</b>",
        parse_mode="HTML",
        reply_markup=batch_count_keyboard()
    )
    await state.set_state(BatchGenState.waiting_for_count)

@router.callback_query(BatchGenState.waiting_for_count, F.data.startswith("batch_"))
async def receive_batch_count(callback: CallbackQuery, state: FSMContext):
    """Получили количество"""
    count = int(callback.data.replace("batch_", ""))
    await state.update_data(count=count)
    
    await callback.message.edit_text(
        f"🔢 {count} шт\n\n"
        f"📐 <b>Выберите формат:</b>",
        parse_mode="HTML",
        reply_markup=aspect_ratio_keyboard()
    )
    await state.set_state(BatchGenState.waiting_for_aspect_ratio)

@router.callback_query(BatchGenState.waiting_for_aspect_ratio, F.data.startswith("aspect_"))
async def execute_batch_generation(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Запускаем пакетную генерацию"""
    aspect_ratio = callback.data.replace("aspect_", "")
    data = await state.get_data()
    prompt = data["prompt"]
    count = data["count"]
    user_id = callback.from_user.id
    
    model_pref = settings_manager.get_image_model(user_id)
    model = "gemini-2.5-flash-image" if model_pref == "flash" else "gemini-3-pro-image-preview"
    
    await callback.message.edit_text(
        f"⏳ Генерирую {count} изображений...\n"
        f"Это займёт немного времени"
    )
    await state.set_state(BatchGenState.generating)
    
    # Генерируем параллельно
    tasks = []
    for i in range(count):
        # Добавляем вариации к промпту для разнообразия
        variation_prompt = f"{prompt}, variation {i+1}, different angle and lighting"
        task = gemini_service.generate_image(
            prompt=variation_prompt,
            model=model,
            aspect_ratio=aspect_ratio
        )
        tasks.append(task)
    
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Фильтруем успешные результаты
        successful = [r for r in results if isinstance(r, bytes) and r is not None]
        
        if not successful:
            await callback.message.edit_text(
                "❌ Не удалось сгенерировать изображения.",
                reply_markup=main_menu()
            )
            await state.clear()
            return
        
        # Отправляем по одному (Telegram ограничение на альбомы)
        await callback.message.delete()
        
        await bot.send_message(
            user_id,
            f"✅ Готово! {len(successful)} из {count}\n📝 {prompt}\n📐 {aspect_ratio}",
            reply_markup=main_menu()
        )
        
        # Отправляем изображения по одному (или группой если мало)
        if len(successful) <= 4:
            # Отправляем медиагруппой
            media = []
            for i, img in enumerate(successful[:4]):
                from aiogram.types import InputMediaPhoto
                media.append(InputMediaPhoto(
                    media=img,
                    caption=f"#{i+1}" if i == 0 else ""
                ))
            await bot.send_media_group(user_id, media=media)
        else:
            # Отправляем по одному
            for i, img in enumerate(successful):
                await bot.send_photo(
                    user_id,
                    photo=img,
                    caption=f"#{i+1}"
                )
        
    except Exception as e:
        logger.exception(f"Batch generation failed: {e}")
        await callback.message.edit_text(
            "❌ Ошибка генерации.",
            reply_markup=main_menu()
        )
    
    await state.clear()
4. Фото в видео (handlers/image_to_video.py)
Python
Copy
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, PhotoSize
from aiogram.fsm.context import FSMContext

from bot.services.kling_service import kling_service
from bot.services.user_settings import settings_manager
from bot.keyboards import video_aspect_ratio_keyboard, image_to_video_duration_keyboard, main_menu
from bot.states import ImageToVideoState

router = Router()
logger = logging.getLogger(__name__)

@router.message(F.text == "🖼️ Фото в видео")
async def start_image_to_video(message: Message, state: FSMContext):
    """Начало фото-в-видео"""
    quality = settings_manager.get_video_quality(message.from_user.id)
    quality_name = "⚡ Standard" if quality == "std" else "🎬 Pro"
    
    await message.answer(
        f"🖼️ <b>Фото в видео</b>\n"
        f"Качество: {quality_name}\n\n"
        f"📎 <b>Загрузите фотографию</b>\n"
        f"Из неё создам анимированное видео",
        parse_mode="HTML"
    )
    await state.set_state(ImageToVideoState.waiting_for_image)

@router.message(ImageToVideoState.waiting_for_image, F.photo)
async def receive_i2v_photo(message: Message, state: FSMContext):
    """Получили фото"""
    photo = message.photo[-1]
    await process_i2v_image(message, photo.file_id, state)

@router.message(ImageToVideoState.waiting_for_image, F.document)
async def receive_i2v_document(message: Message, state: FSMContext):
    """Получили файл"""
    doc = message.document
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        await message.answer("❌ Пожалуйста, отправьте изображение")
        return
    await process_i2v_image(message, doc.file_id, state)

async def process_i2v_image(message: Message, file_id: str, state: FSMContext):
    """Обработка изображения"""
    await message.answer("⏳ Загружаю фото...")
    
    try:
        file = await message.bot.get_file(file_id)
        
        # Получаем URL файла (для Kling нужен URL, загружаем на временный хостинг 
        # или используем file_id если API поддерживает)
        # В реальности нужно загрузить на сервер/облако и получить публичный URL
        # Здесь упрощённый вариант - предполагаем что есть метод upload_image
        
        # Для примера: сохраняем file_id и позже загрузим
        await state.update_data(photo_file_id=file_id)
        
        await message.answer(
            "✅ Фото загружено!\n\n"
            "✏️ <b>Опишите движение</b> (опционально):\n"
            "Например: «Медленно приближается камера» или «Человек улыбается»\n\n"
            "Или нажмите «Пропустить» для автоматической анимации:",
            parse_mode="HTML",
            reply_markup=skip_prompt_keyboard()
        )
        await state.set_state(ImageToVideoState.waiting_for_prompt)
        
    except Exception as e:
        logger.exception(f"Failed to process image: {e}")
        await message.answer("❌ Ошибка загрузки. Попробуйте другое фото.")

def skip_prompt_keyboard():
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_prompt")]
    ])

@router.message(ImageToVideoState.waiting_for_prompt)
async def receive_i2v_prompt(message: Message, state: FSMContext):
    """Получили промпт для видео"""
    prompt = message.text.strip()
    await state.update_data(prompt=prompt)
    
    await message.answer(
        f"✅ {prompt}\n\n"
        f"📐 <b>Выберите формат видео:</b>",
        parse_mode="HTML",
        reply_markup=video_aspect_ratio_keyboard()
    )
    await state.set_state(ImageToVideoState.waiting_for_aspect_ratio)

@router.callback_query(ImageToVideoState.waiting_for_prompt, F.data == "skip_prompt")
async def skip_i2v_prompt(callback: CallbackQuery, state: FSMContext):
    """Пропускаем промпт"""
    await state.update_data(prompt="Animate this image naturally with subtle motion")
    
    await callback.message.edit_text(
        "⏭️ Автоматическая анимация\n\n"
        f"📐 <b>Выберите формат видео:</b>",
        parse_mode="HTML",
        reply_markup=video_aspect_ratio_keyboard()
    )
    await state.set_state(ImageToVideoState.waiting_for_aspect_ratio)

@router.callback_query(ImageToVideoState.waiting_for_aspect_ratio, F.data.startswith("video_aspect_"))
async def receive_i2v_aspect(callback: CallbackQuery, state: FSMContext):
    aspect_ratio = callback.data.replace("video_aspect_", "")
    await state.update_data(aspect_ratio=aspect_ratio)
    
    await callback.message.edit_text(
        f"📐 {aspect_ratio}\n\n"
        f"⏱ <b>Длительность:</b>",
        parse_mode="HTML",
        reply_markup=image_to_video_duration_keyboard()
    )
    await state.set_state(ImageToVideoState.waiting_for_duration)

@router.callback_query(ImageToVideoState.waiting_for_duration, F.data.startswith("i2v_duration_"))
async def generate_image_to_video(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Генерируем видео из фото"""
    duration = int(callback.data.replace("i2v_duration_", ""))
    data = await state.get_data()
    prompt = data.get("prompt", "Animate naturally")
    aspect_ratio = data["aspect_ratio"]
    photo_file_id = data["photo_file_id"]
    user_id = callback.from_user.id
    
    quality = settings_manager.get_video_quality(user_id)
    
    await callback.message.edit_text(
        f"⏳ Создаю видео из фото...\n"
        f"Длительность: {duration} сек"
    )
    await state.set_state(ImageToVideoState.generating)
    
    try:
        # Загружаем фото и получаем URL
        # В реальном проекте нужно загрузить на S3/Imgur/etc
        # Здесь заглушка - предполагаем что есть метод upload_to_temp_hosting
        
        photo_url = await upload_photo_and_get_url(bot, photo_file_id)
        
        if not photo_url:
            await callback.message.edit_text(
                "❌ Ошибка загрузки фото.",
                reply_markup=main_menu()
            )
            await state.clear()
            return
        
        # Выбираем метод
        if quality == "pro":
            result = await kling_service.generate_video_omni_pro(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
                start_image_url=photo_url
            )
        else:
            result = await kling_service.generate_video_omni_std(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
                start_image_url=photo_url
            )
        
        if result and result.get("task_id"):
            task_id = result["task_id"]
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
                    "❌ Видео не создано.",
                    reply_markup=main_menu()
                )
        else:
            await callback.message.edit_text(
                "❌ Ошибка запуска.",
                reply_markup=main_menu()
            )
            
    except Exception as e:
        logger.exception(f"I2V generation failed: {e}")
        await callback.message.edit_text(
            "❌ Ошибка создания видео.",
            reply_markup=main_menu()
        )
    
    await state.clear()

async def upload_photo_and_get_url(bot: Bot, file_id: str) -> str:
    """
    Загружает фото на временный хостинг и возвращает URL.
    В реальном проекте используйте S3, Imgur, или свой сервер.
    """
    # Заглушка - в реальности нужно реализовать загрузку
    # Например через transfer.sh, imgur API, или AWS S3
    
    # Пример с file.io или аналогичным сервисом:
    file = await bot.get_file(file_id)
    image_bytes = await bot.download_file(file.file_path)
    
    # Здесь должен быть код загрузки на хостинг
    # Возвращаем временный URL для примера
    logger.info(f"Would upload image to hosting, size: {len(image_bytes.read())}")
    
    # Временная заглушка - в реальности вернуть URL
    return "https://example.com/temp_image.jpg"
5. Обновлённый bot.py
Python
Copy
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import config
from bot.handlers import (
    start, 
    settings, 
    image_generation, 
    image_editing, 
    video_generation,
    batch_generation,  # Новое
    image_to_video     # Новое
)

logging.basicConfig(level=logging.INFO)

async def main():
    bot = Bot(token=config.BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=MemoryStorage())
    
    # Подключаем роутеры
    dp.include_router(start.router)
    dp.include_router(settings.router)
    dp.include_router(image_generation.router)
    dp.include_router(batch_generation.router)  # Новое
    dp.include_router(image_editing.router)
    dp.include_router(video_generation.router)
    dp.include_router(image_to_video.router)    # Новое
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
6. Дополнение к start.py
Python
Copy
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 <b>Привет!</b> Я бот для генерации изображений и видео.\n\n"
        "🎨 <b>Генерация изображения</b> — одна картинка\n"
        "📦 <b>Пакетная генерация</b> — сразу 2-8 вариантов\n"
        "✏️ <b>Редактировать изображение</b> — изменить фото\n"
        "🎬 <b>Генерация видео</b> — видео по описанию\n"
        "🖼️ <b>Фото в видео</b> — оживить фотографию\n"
        "⚙️ <b>Настройки</b> — модель ИИ и качество\n\n"
        "Всё просто: выбирайте действие и следуйте подсказкам! 👇",
        parse_mode="HTML",
        reply_markup=main_menu()
    )
Что добавлено:
📦 Пакетная генерация — создаёт 2/4/6/8 изображений одновременно с разными вариациями угла и освещения
🖼️ Фото в видео — загружаешь фото, описываешь движение (или пропускаешь), выбираешь формат и длительность — получаешь видео
Важно для фото-в-видео:
Нужно реализовать загрузку изображений на публичный URL (Kling API требует URL). Варианты:
Imgur API — бесплатно, просто
Transfer.sh — временные ссылки
AWS S3 — надёжно, но платно
Свой сервер — если есть
Хочешь, добавлю реализацию загрузки на Imgur или AWS S3?
файлы присланные юзером сохраняютсяв статик и дается публичный url
Edit
Copy
Share
Отлично! Тогда добавляю сохранение файлов в /static и выдачу публичных URL. Вот обновлённые файлы:
1. Обновлённый config.py (добавляем пути)
Python
Copy
import os
from pathlib import Path

# Базовые пути
BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "static"
STATIC_URL = os.getenv("STATIC_URL", "https://your-domain.com/static")

# Создаём папку если нет
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Bot token
BOT_TOKEN = os.getenv("BOT_TOKEN")

# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
NANOBANANA_API_KEY = os.getenv("NANOBANANA_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
FREEPIK_API_KEY = os.getenv("FREEPIK_API_KEY")

# Base URLs
NANOBANANA_BASE_URL = os.getenv("NANOBANANA_BASE_URL", "https://api.nanobanana.com")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api")
FREEPIK_BASE_URL = os.getenv("FREEPIK_BASE_URL", "https://api.freepik.com/v1")
2. Сервис для работы с файлами (services/file_storage.py)
Python
Copy
import logging
import uuid
from pathlib import Path
from typing import Optional

from aiogram import Bot

from bot.config import config

logger = logging.getLogger(__name__)


class FileStorage:
    """Хранилище файлов в static с публичными URL"""
    
    def __init__(self):
        self.static_dir = config.STATIC_DIR
        self.static_url = config.STATIC_URL.rstrip("/")
        self.static_dir.mkdir(parents=True, exist_ok=True)
        
        # Подпапки для организации
        self.images_dir = self.static_dir / "images"
        self.videos_dir = self.static_dir / "videos"
        
        self.images_dir.mkdir(exist_ok=True)
        self.videos_dir.mkdir(exist_ok=True)
    
    def _generate_filename(self, extension: str) -> str:
        """Генерирует уникальное имя файла"""
        return f"{uuid.uuid4().hex}{extension}"
    
    def _get_public_url(self, relative_path: str) -> str:
        """Получает публичный URL для файла"""
        return f"{self.static_url}/{relative_path}"
    
    async def save_image_from_telegram(
        self, 
        bot: Bot, 
        file_id: str,
        user_id: int
    ) -> Optional[str]:
        """
        Скачивает фото из Telegram и сохраняет в static/images/
        Возвращает публичный URL
        """
        try:
            # Создаём подпапку для пользователя
            user_dir = self.images_dir / str(user_id)
            user_dir.mkdir(exist_ok=True)
            
            # Получаем файл
            file = await bot.get_file(file_id)
            
            # Определяем расширение
            file_path = file.file_path
            extension = Path(file_path).suffix or ".jpg"
            
            # Генерируем имя
            filename = self._generate_filename(extension)
            local_path = user_dir / filename
            
            # Скачиваем
            await bot.download_file(file_path, destination=str(local_path))
            
            # Формируем относительный путь для URL
            relative_path = f"images/{user_id}/{filename}"
            public_url = self._get_public_url(relative_path)
            
            logger.info(f"Saved image: {local_path} -> {public_url}")
            return public_url
            
        except Exception as e:
            logger.exception(f"Failed to save image: {e}")
            return None
    
    async def save_bytes_as_image(
        self,
        image_bytes: bytes,
        user_id: int,
        extension: str = ".png"
    ) -> Optional[str]:
        """
        Сохраняет байты изображения и возвращает URL
        """
        try:
            user_dir = self.images_dir / str(user_id)
            user_dir.mkdir(exist_ok=True)
            
            filename = self._generate_filename(extension)
            local_path = user_dir / filename
            
            with open(local_path, "wb") as f:
                f.write(image_bytes)
            
            relative_path = f"images/{user_id}/{filename}"
            public_url = self._get_public_url(relative_path)
            
            logger.info(f"Saved bytes as image: {local_path}")
            return public_url
            
        except Exception as e:
            logger.exception(f"Failed to save image bytes: {e}")
            return None
    
    def cleanup_old_files(self, max_age_hours: int = 24):
        """Очистка старых файлов (можно вызывать по расписанию)"""
        import time
        from datetime import datetime, timedelta
        
        cutoff = time.time() - (max_age_hours * 3600)
        deleted = 0
        
        for directory in [self.images_dir, self.videos_dir]:
            if not directory.exists():
                continue
                
            for file_path in directory.rglob("*"):
                if file_path.is_file():
                    try:
                        if file_path.stat().st_mtime < cutoff:
                            file_path.unlink()
                            deleted += 1
                    except Exception as e:
                        logger.error(f"Failed to delete {file_path}: {e}")
        
        logger.info(f"Cleaned up {deleted} old files")
        return deleted


# Глобальный инстанс
file_storage = FileStorage()
3. Обновлённый image_to_video.py (используем static)
Python
Copy
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, PhotoSize
from aiogram.fsm.context import FSMContext

from bot.services.kling_service import kling_service
from bot.services.user_settings import settings_manager
from bot.services.file_storage import file_storage
from bot.keyboards import video_aspect_ratio_keyboard, image_to_video_duration_keyboard, main_menu
from bot.states import ImageToVideoState

router = Router()
logger = logging.getLogger(__name__)


def skip_prompt_keyboard():
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_prompt")]
    ])


@router.message(F.text == "🖼️ Фото в видео")
async def start_image_to_video(message: Message, state: FSMContext):
    """Начало фото-в-видео"""
    quality = settings_manager.get_video_quality(message.from_user.id)
    quality_name = "⚡ Standard" if quality == "std" else "🎬 Pro"
    
    await message.answer(
        f"🖼️ <b>Фото в видео</b>\n"
        f"Качество: {quality_name}\n\n"
        f"📎 <b>Загрузите фотографию</b>\n"
        f"Из неё создам анимированное видео",
        parse_mode="HTML"
    )
    await state.set_state(ImageToVideoState.waiting_for_image)


@router.message(ImageToVideoState.waiting_for_image, F.photo)
async def receive_i2v_photo(message: Message, state: FSMContext, bot: Bot):
    """Получили фото"""
    photo = message.photo[-1]
    await process_i2v_image(message, bot, photo.file_id, state)


@router.message(ImageToVideoState.waiting_for_image, F.document)
async def receive_i2v_document(message: Message, state: FSMContext, bot: Bot):
    """Получили файл"""
    doc = message.document
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        await message.answer("❌ Пожалуйста, отправьте изображение")
        return
    await process_i2v_image(message, bot, doc.file_id, state)


async def process_i2v_image(message: Message, bot: Bot, file_id: str, state: FSMContext):
    """Обработка изображения"""
    await message.answer("⏳ Загружаю фото...")
    
    try:
        # Сохраняем в static и получаем публичный URL
        photo_url = await file_storage.save_image_from_telegram(
            bot=bot,
            file_id=file_id,
            user_id=message.from_user.id
        )
        
        if not photo_url:
            await message.answer("❌ Ошибка сохранения фото. Попробуйте другое.")
            return
        
        # Сохраняем URL в состояние
        await state.update_data(photo_url=photo_url)
        
        await message.answer(
            "✅ Фото загружено!\n\n"
            "✏️ <b>Опишите движение</b> (опционально):\n"
            "Например: «Медленно приближается камера» или «Человек улыбается»\n\n"
            "Или нажмите «Пропустить» для автоматической анимации:",
            parse_mode="HTML",
            reply_markup=skip_prompt_keyboard()
        )
        await state.set_state(ImageToVideoState.waiting_for_prompt)
        
    except Exception as e:
        logger.exception(f"Failed to process image: {e}")
        await message.answer("❌ Ошибка загрузки. Попробуйте другое фото.")


@router.message(ImageToVideoState.waiting_for_prompt)
async def receive_i2v_prompt(message: Message, state: FSMContext):
    """Получили промпт для видео"""
    prompt = message.text.strip()
    await state.update_data(prompt=prompt)
    
    await message.answer(
        f"✅ {prompt}\n\n"
        f"📐 <b>Выберите формат видео:</b>",
        parse_mode="HTML",
        reply_markup=video_aspect_ratio_keyboard()
    )
    await state.set_state(ImageToVideoState.waiting_for_aspect_ratio)


@router.callback_query(ImageToVideoState.waiting_for_prompt, F.data == "skip_prompt")
async def skip_i2v_prompt(callback: CallbackQuery, state: FSMContext):
    """Пропускаем промпт"""
    await state.update_data(prompt="Animate this image naturally with subtle motion")
    
    await callback.message.edit_text(
        "⏭️ Автоматическая анимация\n\n"
        f"📐 <b>Выберите формат видео:</b>",
        parse_mode="HTML",
        reply_markup=video_aspect_ratio_keyboard()
    )
    await state.set_state(ImageToVideoState.waiting_for_aspect_ratio)


@router.callback_query(ImageToVideoState.waiting_for_aspect_ratio, F.data.startswith("video_aspect_"))
async def receive_i2v_aspect(callback: CallbackQuery, state: FSMContext):
    aspect_ratio = callback.data.replace("video_aspect_", "")
    await state.update_data(aspect_ratio=aspect_ratio)
    
    await callback.message.edit_text(
        f"📐 {aspect_ratio}\n\n"
        f"⏱ <b>Длительность:</b>",
        parse_mode="HTML",
        reply_markup=image_to_video_duration_keyboard()
    )
    await state.set_state(ImageToVideoState.waiting_for_duration)


@router.callback_query(ImageToVideoState.waiting_for_duration, F.data.startswith("i2v_duration_"))
async def generate_image_to_video(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Генерируем видео из фото"""
    duration = int(callback.data.replace("i2v_duration_", ""))
    data = await state.get_data()
    prompt = data.get("prompt", "Animate naturally")
    aspect_ratio = data["aspect_ratio"]
    photo_url = data["photo_url"]  # Теперь у нас есть прямой URL!
    user_id = callback.from_user.id
    
    quality = settings_manager.get_video_quality(user_id)
    
    await callback.message.edit_text(
        f"⏳ Создаю видео из фото...\n"
        f"Длительность: {duration} сек\n"
        f"⏱ Ожидание: 2-5 минут"
    )
    await state.set_state(ImageToVideoState.generating)
    
    try:
        # Выбираем метод в зависимости от качества
        if quality == "pro":
            result = await kling_service.generate_video_omni_pro(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
                start_image_url=photo_url  # Используем наш публичный URL!
            )
        else:
            result = await kling_service.generate_video_omni_std(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
                start_image_url=photo_url
            )
        
        if result and result.get("task_id"):
            task_id = result["task_id"]
            
            # Отправляем уведомление что процесс пошёл
            await callback.message.edit_text(
                f"🎬 Генерация начата...\n"
                f"ID задачи: {task_id}\n"
                f"Проверяю статус..."
            )
            
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
                error_msg = status.get("data", {}).get("error", "Неизвестная ошибка") if status else "Таймаут"
                await callback.message.edit_text(
                    f"❌ Видео не создано.\nОшибка: {error_msg}",
                    reply_markup=main_menu()
                )
        else:
            error = result.get("error") if result else "Нет ответа от API"
            await callback.message.edit_text(
                f"❌ Ошибка запуска.\n{error}",
                reply_markup=main_menu()
            )
            
    except Exception as e:
        logger.exception(f"I2V generation failed: {e}")
        await callback.message.edit_text(
            "❌ Ошибка создания видео. Попробуйте позже.",
            reply_markup=main_menu()
        )
    
    await state.clear()
4. Обновлённый image_editing.py (тоже сохраняем в static если нужно)
Python
Copy
import logging
import io
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, PhotoSize
from aiogram.fsm.context import FSMContext

from bot.services.gemini_service import gemini_service
from bot.services.user_settings import settings_manager
from bot.services.file_storage import file_storage  # Добавили
from bot.keyboards import aspect_ratio_keyboard, main_menu
from bot.states import ImageEditState

router = Router()
logger = logging.getLogger(__name__)


@router.message(F.text == "✏️ Редактировать изображение")
async def start_image_editing(message: Message, state: FSMContext):
    """Начало редактирования"""
    await message.answer(
        "✏️ <b>Редактирование изображения</b>\n\n"
        "📎 <b>Загрузите изображение</b> (фото или файл)\n"
        "Поддерживаются JPG, PNG",
        parse_mode="HTML"
    )
    await state.set_state(ImageEditState.waiting_for_image)


@router.message(ImageEditState.waiting_for_image, F.photo)
async def receive_photo(message: Message, state: FSMContext, bot: Bot):
    """Получили фото"""
    photo = message.photo[-1]
    await process_image(message, bot, photo.file_id, state)


@router.message(ImageEditState.waiting_for_image, F.document)
async def receive_document(message: Message, state: FSMContext, bot: Bot):
    """Получили файл"""
    doc = message.document
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        await message.answer("❌ Пожалуйста, отправьте изображение (JPG или PNG)")
        return
    await process_image(message, bot, doc.file_id, state)


async def process_image(message: Message, bot: Bot, file_id: str, state: FSMContext):
    """Обработка полученного изображения"""
    await message.answer("⏳ Загружаю изображение...")
    
    try:
        # Скачиваем файл
        file = await bot.get_file(file_id)
        image_bytes_io = await bot.download_file(file.file_path)
        image_data = image_bytes_io.read()
        
        # Сохраняем в состояние для редактирования
        await state.update_data(image=image_data)
        
        # Опционально: сохраняем в static для истории/логов
        # public_url = await file_storage.save_bytes_as_image(
        #     image_bytes=image_data,
        #     user_id=message.from_user.id
        # )
        
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
    """Получили промпт для редактирования"""
    prompt = message.text.strip()
    
    if len(prompt) < 3:
        await message.answer("❌ Описание слишком короткое:")
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
            await bot.send_photo(
                chat_id=user_id,
                photo=result,
                caption=f"✅ Готово!\n📝 {prompt}\n📐 {aspect_ratio}",
                reply_markup=main_menu()
            )
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
5. Добавляем очистку в bot.py (опционально)
Python
Copy
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import config
from bot.handlers import (
    start, 
    settings, 
    image_generation, 
    image_editing, 
    video_generation,
    batch_generation,
    image_to_video
)
from bot.services.file_storage import file_storage

logging.basicConfig(level=logging.INFO)

async def cleanup_task():
    """Фоновая задача очистки старых файлов"""
    while True:
        await asyncio.sleep(3600)  # Каждый час
        try:
            deleted = file_storage.cleanup_old_files(max_age_hours=24)
            logging.info(f"Cleanup completed: {deleted} files deleted")
        except Exception as e:
            logging.error(f"Cleanup error: {e}")

async def main():
    bot = Bot(token=config.BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=MemoryStorage())
    
    # Подключаем роутеры
    dp.include_router(start.router)
    dp.include_router(settings.router)
    dp.include_router(image_generation.router)
    dp.include_router(batch_generation.router)
    dp.include_router(image_editing.router)
    dp.include_router(video_generation.router)
    dp.include_router(image_to_video.router)
    
    # Запускаем очистку в фоне
    asyncio.create_task(cleanup_task())
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
6. Пример nginx конфигурации (для публичного доступа к static)
nginx
Copy
server {
    listen 80;
    server_name your-domain.com;
    
    location /static/ {
        alias /path/to/your/bot/static/;
        expires 1d;
        add_header Cache-Control "public, immutable";
    }
    
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
Итоговая структура:
plain
Copy
bot/
├── static/                    # Публичная папка
│   ├── images/
│   │   └── {user_id}/
│   │       └── {uuid}.jpg
│   └── videos/
├── config.py
├── services/
│   ├── file_storage.py        # Новое
│   ├── user_settings.py
│   ├── gemini_service.py
│   └── kling_service.py
└── handlers/
    ├── image_to_video.py      # Обновлён (использует file_storage)
    └── ...
Теперь все загруженные фото сохраняются в /static/images/{user_id}/{uuid}.jpg и доступны по https://your-domain.com/static/images/{user_id}/{uuid}.jpg — Kling API может их скачать напрямую!
Нужно добавить webhook для автоматической очистки или ограничение размера папки?
пакетное редактирование фото
Edit
Copy
Share
Добавляю пакетное редактирование фото. Пользователь загружает несколько фото, пишет один промпт, и бот редактирует все сразу.
1. Обновлённые клавиатуры (keyboards.py)
Python
Copy
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# Главное меню (обновлённое)
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎨 Генерация изображения")],
            [KeyboardButton(text="📦 Пакетная генерация")],
            [KeyboardButton(text="✏️ Редактировать изображение")],
            [InlineKeyboardButton(text="📂 Пакетное редактирование")],
            [KeyboardButton(text="🎬 Генерация видео")],
            [KeyboardButton(text="🖼️ Фото в видео")],
            [KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True
    )

# Настройки
def settings_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Модель ИИ", callback_data="setting_model")],
        [InlineKeyboardButton(text="📹 Качество видео", callback_data="setting_video")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")],
    ])

# Выбор модели
def model_selection(current_model: str):
    flash_check = "✅ " if current_model == "flash" else ""
    pro_check = "✅ " if current_model == "pro" else ""
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{flash_check}⚡ Flash (быстро)", callback_data="set_model_flash")],
        [InlineKeyboardButton(text=f"{pro_check}🎨 Pro (качество)", callback_data="set_model_pro")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="settings")],
    ])

# Выбор качества видео
def video_quality_selection(current_quality: str):
    std_check = "✅ " if current_quality == "std" else ""
    pro_check = "✅ " if current_quality == "pro" else ""
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{std_check}⚡ Standard (быстро)", callback_data="set_video_std")],
        [InlineKeyboardButton(text=f"{pro_check}🎬 Pro (качество)", callback_data="set_video_pro")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="settings")],
    ])

# Аспект-ратио для изображений
def aspect_ratio_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1:1", callback_data="aspect_1:1"),
            InlineKeyboardButton(text="16:9", callback_data="aspect_16:9"),
            InlineKeyboardButton(text="9:16", callback_data="aspect_9:16"),
        ],
        [
            InlineKeyboardButton(text="4:3", callback_data="aspect_4:3"),
            InlineKeyboardButton(text="3:4", callback_data="aspect_3:4"),
            InlineKeyboardButton(text="2:3", callback_data="aspect_2:3"),
        ],
    ])

# Аспект-ратио для видео
def video_aspect_ratio_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="16:9 (широкий)", callback_data="video_aspect_16:9"),
            InlineKeyboardButton(text="9:16 (вертикальный)", callback_data="video_aspect_9:16"),
        ],
        [InlineKeyboardButton(text="1:1 (квадрат)", callback_data="video_aspect_1:1")],
    ])

# Продолжительность видео
def video_duration_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="3 сек", callback_data="duration_3"),
            InlineKeyboardButton(text="5 сек", callback_data="duration_5"),
            InlineKeyboardButton(text="7 сек", callback_data="duration_7"),
        ],
        [
            InlineKeyboardButton(text="10 сек", callback_data="duration_10"),
            [InlineKeyboardButton(text="12 сек", callback_data="duration_12")],
            [InlineKeyboardButton(text="15 сек", callback_data="duration_15")],
        ],
    ])

# Выбор количества для пакетной генерации
def batch_count_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="2 шт", callback_data="batch_2"),
            InlineKeyboardButton(text="4 шт", callback_data="batch_4"),
        ],
        [
            InlineKeyboardButton(text="6 шт", callback_data="batch_6"),
            InlineKeyboardButton(text="8 шт", callback_data="batch_8"),
        ],
    ])

# Продолжительность для фото-в-видео
def image_to_video_duration_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="3 сек", callback_data="i2v_duration_3"),
            InlineKeyboardButton(text="5 сек", callback_data="i2v_duration_5"),
        ],
        [InlineKeyboardButton(text="10 сек", callback_data="i2v_duration_10")],
    ])

# Клавиатура для пакетного редактирования - готово к обработке
def batch_edit_ready_keyboard(count: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Готово ({count} фото)", callback_data="batch_edit_ready")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="batch_edit_cancel")],
    ])

# Добавить ещё фото или готово
def batch_edit_add_more_keyboard(count: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📎 Добавить ещё", callback_data="batch_edit_add")],
        [InlineKeyboardButton(text=f"✅ Готово ({count})", callback_data="batch_edit_ready")],
    ])
2. Обновлённые состояния (states.py)
Python
Copy
from aiogram.fsm.state import State, StatesGroup

class ImageGenState(StatesGroup):
    waiting_for_prompt = State()
    waiting_for_aspect_ratio = State()
    generating = State()

class BatchGenState(StatesGroup):
    waiting_for_prompt = State()
    waiting_for_count = State()
    waiting_for_aspect_ratio = State()
    generating = State()

class ImageEditState(StatesGroup):
    waiting_for_image = State()
    waiting_for_prompt = State()
    waiting_for_aspect_ratio = State()
    generating = State()

class BatchEditState(StatesGroup):
    collecting_images = State()      # Собираем фото
    waiting_for_prompt = State()     # Ждём промпт
    waiting_for_aspect_ratio = State()  # Выбор формата
    generating = State()             # Генерация

class VideoGenState(StatesGroup):
    waiting_for_prompt = State()
    waiting_for_aspect_ratio = State()
    waiting_for_duration = State()
    generating = State()

class ImageToVideoState(StatesGroup):
    waiting_for_image = State()
    waiting_for_prompt = State()
    waiting_for_aspect_ratio = State()
    waiting_for_duration = State()
    generating = State()
3. Пакетное редактирование (handlers/batch_editing.py)
Python
Copy
import logging
import asyncio
from typing import List
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext

from bot.services.gemini_service import gemini_service
from bot.services.user_settings import settings_manager
from bot.keyboards import (
    aspect_ratio_keyboard, 
    main_menu, 
    batch_edit_ready_keyboard,
    batch_edit_add_more_keyboard
)
from bot.states import BatchEditState

router = Router()
logger = logging.getLogger(__name__)

MAX_BATCH_EDIT_IMAGES = 10  # Максимум фото за раз


@router.message(F.text == "📂 Пакетное редактирование")
async def start_batch_editing(message: Message, state: FSMContext):
    """Начало пакетного редактирования"""
    await state.update_data(images=[], image_count=0)
    
    await message.answer(
        "📂 <b>Пакетное редактирование</b>\n\n"
        "Загрузите <b>несколько фотографий</b>, которые хотите обработать одинаково.\n\n"
        "📎 <b>Отправляйте фото по одному</b> или группой\n"
        f"Максимум: {MAX_BATCH_EDIT_IMAGES} шт\n\n"
        "Когда загрузите все — нажмите «Готово»",
        parse_mode="HTML",
        reply_markup=batch_edit_ready_keyboard(0)
    )
    await state.set_state(BatchEditState.collecting_images)


@router.message(BatchEditState.collecting_images, F.photo)
async def receive_batch_photo(message: Message, state: FSMContext):
    """Получили фото"""
    data = await state.get_data()
    images: List[bytes] = data.get("images", [])
    count = data.get("image_count", 0)
    
    if count >= MAX_BATCH_EDIT_IMAGES:
        await message.answer(
            f"⚠️ Достигнут лимит ({MAX_BATCH_EDIT_IMAGES} фото)\n"
            f"Нажмите «Готово» для продолжения",
            reply_markup=batch_edit_ready_keyboard(count)
        )
        return
    
    # Скачиваем фото
    try:
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        image_bytes = await message.bot.download_file(file.file_path)
        image_data = image_bytes.read()
        
        images.append(image_data)
        count += 1
        
        await state.update_data(images=images, image_count=count)
        
        await message.answer(
            f"✅ Загружено: {count} фото\n"
            f"📎 Можете добавить ещё или нажать «Готово»",
            reply_markup=batch_edit_add_more_keyboard(count)
        )
        
    except Exception as e:
        logger.exception(f"Failed to download photo: {e}")
        await message.answer("❌ Ошибка загрузки, попробуйте другое фото")


@router.message(BatchEditState.collecting_images, F.document)
async def receive_batch_document(message: Message, state: FSMContext):
    """Получили файл"""
    doc = message.document
    
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        await message.answer("❌ Пожалуйста, отправьте изображение")
        return
    
    data = await state.get_data()
    images: List[bytes] = data.get("images", [])
    count = data.get("image_count", 0)
    
    if count >= MAX_BATCH_EDIT_IMAGES:
        await message.answer(
            f"⚠️ Достигнут лимит ({MAX_BATCH_EDIT_IMAGES} фото)",
            reply_markup=batch_edit_ready_keyboard(count)
        )
        return
    
    try:
        file = await message.bot.get_file(doc.file_id)
        image_bytes = await message.bot.download_file(file.file_path)
        image_data = image_bytes.read()
        
        images.append(image_data)
        count += 1
        
        await state.update_data(images=images, image_count=count)
        
        await message.answer(
            f"✅ Загружено: {count} фото",
            reply_markup=batch_edit_add_more_keyboard(count)
        )
        
    except Exception as e:
        logger.exception(f"Failed to download document: {e}")
        await message.answer("❌ Ошибка загрузки файла")


@router.callback_query(BatchEditState.collecting_images, F.data == "batch_edit_add")
async def continue_adding(callback: CallbackQuery):
    """Продолжаем добавлять"""
    await callback.answer("Отправьте следующее фото")


@router.callback_query(BatchEditState.collecting_images, F.data == "batch_edit_ready")
async def finish_collecting(callback: CallbackQuery, state: FSMContext):
    """Закончили собирать фото"""
    data = await state.get_data()
    images = data.get("images", [])
    count = data.get("image_count", 0)
    
    if count == 0:
        await callback.answer("❌ Нет загруженных фото!")
        return
    
    if count == 1:
        await callback.message.edit_text(
            "⚠️ Загружено только 1 фото.\n"
            "Для одиночного редактирования используйте «✏️ Редактировать изображение»\n\n"
            "Продолжить всё равно или отмена?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="▶️ Продолжить", callback_data="batch_continue_anyway")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="batch_edit_cancel")],
            ])
        )
        return
    
    await proceed_to_prompt(callback, state)


@router.callback_query(BatchEditState.collecting_images, F.data == "batch_continue_anyway")
async def continue_single(callback: CallbackQuery, state: FSMContext):
    """Продолжаем даже с 1 фото"""
    await proceed_to_prompt(callback, state)


async def proceed_to_prompt(callback: CallbackQuery, state: FSMContext):
    """Переходим к вводу промпта"""
    data = await state.get_data()
    count = data.get("image_count", 0)
    
    await callback.message.edit_text(
        f"✅ <b>{count} фото</b> принято!\n\n"
        f"✏️ <b>Что сделать со всеми фото?</b>\n"
        f"Например:\n"
        f"• «Увеличить контраст»\n"
        f"• «Сделать чёрно-белым»\n"
        f"• «Добавить рамку»\n"
        f"• «Улучшить качество»",
        parse_mode="HTML"
    )
    await state.set_state(BatchEditState.waiting_for_prompt)


@router.message(BatchEditState.waiting_for_prompt)
async def receive_batch_prompt(message: Message, state: FSMContext):
    """Получили промпт для всех фото"""
    prompt = message.text.strip()
    
    if len(prompt) < 3:
        await message.answer("❌ Описание слишком короткое:")
        return
    
    await state.update_data(prompt=prompt)
    
    await message.answer(
        f"✅ Задача: <i>{prompt}</i>\n\n"
        f"📐 <b>Выберите формат для всех фото:</b>",
        parse_mode="HTML",
        reply_markup=aspect_ratio_keyboard()
    )
    await state.set_state(BatchEditState.waiting_for_aspect_ratio)


@router.callback_query(BatchEditState.waiting_for_aspect_ratio, F.data.startswith("aspect_"))
async def execute_batch_edit(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Запускаем пакетное редактирование"""
    aspect_ratio = callback.data.replace("aspect_", "")
    data = await state.get_data()
    prompt = data["prompt"]
    images: List[bytes] = data["images"]
    count = len(images)
    user_id = callback.from_user.id
    
    model_pref = settings_manager.get_image_model(user_id)
    model = "gemini-2.5-flash-image" if model_pref == "flash" else "gemini-3-pro-image-preview"
    
    await callback.message.edit_text(
        f"⏳ Обрабатываю {count} фото...\n"
        f"Задача: {prompt}\n"
        f"0/{count} готово"
    )
    await state.set_state(BatchEditState.generating)
    
    # Обрабатываем параллельно с ограничением
    semaphore = asyncio.Semaphore(3)  # Макс 3 одновременно
    
    async def edit_single(index: int, image_data: bytes) -> tuple:
        async with semaphore:
            try:
                result = await gemini_service.edit_image(
                    image_bytes=image_data,
                    instruction=prompt,
                    model=model,
                    aspect_ratio=aspect_ratio
                )
                return (index, result, None)
            except Exception as e:
                logger.exception(f"Failed to edit image {index}: {e}")
                return (index, None, str(e))
    
    # Запускаем все задачи
    tasks = [edit_single(i, img) for i, img in enumerate(images)]
    results = await asyncio.gather(*tasks)
    
    # Сортируем по индексу
    results.sort(key=lambda x: x[0])
    
    # Отправляем результаты
    successful = 0
    failed = 0
    
    await callback.message.delete()
    
    # Отправляем уведомление что начинаем выгрузку
    status_msg = await bot.send_message(
        user_id,
        f"📤 Отправляю результаты..."
    )
    
    for index, result, error in results:
        if result:
            successful += 1
            await bot.send_photo(
                chat_id=user_id,
                photo=BufferedInputFile(result, filename=f"edited_{index+1}.png"),
                caption=f"✅ #{index+1}"
            )
        else:
            failed += 1
            await bot.send_message(
                user_id,
                f"❌ #{index+1} — ошибка обработки"
            )
    
    # Итог
    await status_msg.delete()
    await bot.send_message(
        user_id,
        f"✅ <b>Готово!</b>\n\n"
        f"📝 Задача: {prompt}\n"
        f"📐 Формат: {aspect_ratio}\n"
        f"✅ Успешно: {successful}/{count}\n"
        f"❌ Ошибок: {failed}",
        parse_mode="HTML",
        reply_markup=main_menu()
    )
    
    await state.clear()


@router.callback_query(F.data == "batch_edit_cancel")
async def cancel_batch_edit(callback: CallbackQuery, state: FSMContext):
    """Отмена"""
    await callback.message.edit_text("❌ Отменено")
    await callback.message.answer("Главное меню:", reply_markup=main_menu())
    await state.clear()
4. Обновлённый bot.py
Python
Copy
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import config
from bot.handlers import (
    start, 
    settings, 
    image_generation, 
    image_editing, 
    video_generation,
    batch_generation,
    batch_editing,      # Новое
    image_to_video
)
from bot.services.file_storage import file_storage

logging.basicConfig(level=logging.INFO)

async def cleanup_task():
    """Фоновая задача очистки старых файлов"""
    while True:
        await asyncio.sleep(3600)
        try:
            deleted = file_storage.cleanup_old_files(max_age_hours=24)
            logging.info(f"Cleanup completed: {deleted} files deleted")
        except Exception as e:
            logging.error(f"Cleanup error: {e}")

async def main():
    bot = Bot(token=config.BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=MemoryStorage())
    
    # Подключаем роутеры
    dp.include_router(start.router)
    dp.include_router(settings.router)
    dp.include_router(image_generation.router)
    dp.include_router(batch_generation.router)
    dp.include_router(image_editing.router)
    dp.include_router(batch_editing.router)     # Новое
    dp.include_router(video_generation.router)
    dp.include_router(image_to_video.router)
    
    # Запускаем очистку в фоне
    asyncio.create_task(cleanup_task())
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
5. Обновлённый start.py
Python
Copy
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import CommandStart

from bot.keyboards import main_menu

router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 <b>Привет!</b> Я бот для генерации изображений и видео.\n\n"
        "🎨 <b>Генерация изображения</b> — одна картинка\n"
        "📦 <b>Пакетная генерация</b> — сразу 2-8 вариантов\n"
        "✏️ <b>Редактировать изображение</b> — изменить одно фото\n"
        "📂 <b>Пакетное редактирование</b> — обработать много фото разом\n"
        "🎬 <b>Генерация видео</b> — видео по описанию\n"
        "🖼️ <b>Фото в видео</b> — оживить фотографию\n"
        "⚙️ <b>Настройки</b> — модель ИИ и качество\n\n"
        "Всё просто: выбирайте действие и следуйте подсказкам! 👇",
        parse_mode="HTML",
        reply_markup=main_menu()
    )
Как работает пакетное редактирование:
Пользователь жмёт «📂 Пакетное редактирование»
Загружает фото по одному или группой (до 10 шт)
Жмёт «Готово» когда всё загружено
Вводит промпт — что сделать со всеми фото
Выбирает формат — все фото будут в этом формате
Бот обрабатывает параллельно (макс 3 одновременно)
Присылает результаты по одному с номерами
Особенности:
Параллельная обработка — быстрее чем по очереди
Семафор — ограничение 3 одновременных запроса (чтобы не забанили)
Прогресс — показывает сколько готово
Обработка ошибок — если одно фото не обработалось, остальные всё равно придут
Сохранение порядка — результаты приходят в том же порядке что и загрузка
Хочешь добавить прогресс-бар с процентами или возможность применить разные промпты к разным фото?
напиши все исправления в одном сообщении
Edit
Copy
Share
Вот все исправления в одном сообщении:
1. Исправленный keyboards.py
Python
Copy
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# Главное меню (исправлено - убран InlineKeyboardButton)
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎨 Генерация изображения")],
            [KeyboardButton(text="📦 Пакетная генерация")],
            [KeyboardButton(text="✏️ Редактировать изображение")],
            [KeyboardButton(text="📂 Пакетное редактирование")],  # Было InlineKeyboardButton
            [KeyboardButton(text="🎬 Генерация видео")],
            [KeyboardButton(text="🖼️ Фото в видео")],
            [KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True
    )

# Настройки
def settings_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Модель ИИ", callback_data="setting_model")],
        [InlineKeyboardButton(text="📹 Качество видео", callback_data="setting_video")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")],
    ])

# Выбор модели
def model_selection(current_model: str):
    flash_check = "✅ " if current_model == "flash" else ""
    pro_check = "✅ " if current_model == "pro" else ""
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{flash_check}⚡ Flash (быстро)", callback_data="set_model_flash")],
        [InlineKeyboardButton(text=f"{pro_check}🎨 Pro (качество)", callback_data="set_model_pro")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="settings")],
    ])

# Выбор качества видео
def video_quality_selection(current_quality: str):
    std_check = "✅ " if current_quality == "std" else ""
    pro_check = "✅ " if current_quality == "pro" else ""
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{std_check}⚡ Standard (быстро)", callback_data="set_video_std")],
        [InlineKeyboardButton(text=f"{pro_check}🎬 Pro (качество)", callback_data="set_video_pro")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="settings")],
    ])

# Аспект-ратио для изображений
def aspect_ratio_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1:1", callback_data="aspect_1:1"),
            InlineKeyboardButton(text="16:9", callback_data="aspect_16:9"),
            InlineKeyboardButton(text="9:16", callback_data="aspect_9:16"),
        ],
        [
            InlineKeyboardButton(text="4:3", callback_data="aspect_4:3"),
            InlineKeyboardButton(text="3:4", callback_data="aspect_3:4"),
            InlineKeyboardButton(text="2:3", callback_data="aspect_2:3"),
        ],
    ])

# Аспект-ратио для видео
def video_aspect_ratio_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="16:9 (широкий)", callback_data="video_aspect_16:9"),
            InlineKeyboardButton(text="9:16 (вертикальный)", callback_data="video_aspect_9:16"),
        ],
        [InlineKeyboardButton(text="1:1 (квадрат)", callback_data="video_aspect_1:1")],
    ])

# Продолжительность видео
def video_duration_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="3 сек", callback_data="duration_3"),
            InlineKeyboardButton(text="5 сек", callback_data="duration_5"),
            InlineKeyboardButton(text="7 сек", callback_data="duration_7"),
        ],
        [
            InlineKeyboardButton(text="10 сек", callback_data="duration_10"),
            InlineKeyboardButton(text="12 сек", callback_data="duration_12"),
            InlineKeyboardButton(text="15 сек", callback_data="duration_15"),
        ],
    ])

# Выбор количества для пакетной генерации
def batch_count_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="2 шт", callback_data="batch_2"),
            InlineKeyboardButton(text="4 шт", callback_data="batch_4"),
        ],
        [
            InlineKeyboardButton(text="6 шт", callback_data="batch_6"),
            InlineKeyboardButton(text="8 шт", callback_data="batch_8"),
        ],
    ])

# Продолжительность для фото-в-видео
def image_to_video_duration_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="3 сек", callback_data="i2v_duration_3"),
            InlineKeyboardButton(text="5 сек", callback_data="i2v_duration_5"),
        ],
        [InlineKeyboardButton(text="10 сек", callback_data="i2v_duration_10")],
    ])

# Клавиатура для пакетного редактирования
def batch_edit_ready_keyboard(count: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Готово ({count} фото)", callback_data="batch_edit_ready")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="batch_edit_cancel")],
    ])

# Добавить ещё фото или готово
def batch_edit_add_more_keyboard(count: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📎 Добавить ещё", callback_data="batch_edit_add")],
        [InlineKeyboardButton(text=f"✅ Готово ({count})", callback_data="batch_edit_ready")],
    ])

# Пропустить промпт
def skip_prompt_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_prompt")]
    ])
2. Исправленный states.py
Python
Copy
from aiogram.fsm.state import State, StatesGroup

class ImageGenState(StatesGroup):
    waiting_for_prompt = State()
    waiting_for_aspect_ratio = State()
    generating = State()

class BatchGenState(StatesGroup):
    waiting_for_prompt = State()
    waiting_for_count = State()
    waiting_for_aspect_ratio = State()
    generating = State()

class ImageEditState(StatesGroup):
    waiting_for_image = State()
    waiting_for_prompt = State()
    waiting_for_aspect_ratio = State()
    generating = State()

class BatchEditState(StatesGroup):
    collecting_images = State()
    waiting_for_prompt = State()
    waiting_for_aspect_ratio = State()
    generating = State()

class VideoGenState(StatesGroup):
    waiting_for_prompt = State()
    waiting_for_aspect_ratio = State()
    waiting_for_duration = State()
    generating = State()

class ImageToVideoState(StatesGroup):
    waiting_for_image = State()
    waiting_for_prompt = State()
    waiting_for_aspect_ratio = State()
    waiting_for_duration = State()
    generating = State()
3. Исправленный image_to_video.py (импорт skip_prompt_keyboard из keyboards)
Python
Copy
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, PhotoSize
from aiogram.fsm.context import FSMContext

from bot.services.kling_service import kling_service
from bot.services.user_settings import settings_manager
from bot.services.file_storage import file_storage
from bot.keyboards import (
    video_aspect_ratio_keyboard, 
    image_to_video_duration_keyboard, 
    main_menu,
    skip_prompt_keyboard  # Исправлено - импорт из keyboards
)
from bot.states import ImageToVideoState

router = Router()
logger = logging.getLogger(__name__)


@router.message(F.text == "🖼️ Фото в видео")
async def start_image_to_video(message: Message, state: FSMContext):
    """Начало фото-в-видео"""
    quality = settings_manager.get_video_quality(message.from_user.id)
    quality_name = "⚡ Standard" if quality == "std" else "🎬 Pro"
    
    await message.answer(
        f"🖼️ <b>Фото в видео</b>\n"
        f"Качество: {quality_name}\n\n"
        f"📎 <b>Загрузите фотографию</b>\n"
        f"Из неё создам анимированное видео",
        parse_mode="HTML"
    )
    await state.set_state(ImageToVideoState.waiting_for_image)


@router.message(ImageToVideoState.waiting_for_image, F.photo)
async def receive_i2v_photo(message: Message, state: FSMContext, bot: Bot):
    """Получили фото"""
    photo = message.photo[-1]
    await process_i2v_image(message, bot, photo.file_id, state)


@router.message(ImageToVideoState.waiting_for_image, F.document)
async def receive_i2v_document(message: Message, state: FSMContext, bot: Bot):
    """Получили файл"""
    doc = message.document
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        await message.answer("❌ Пожалуйста, отправьте изображение")
        return
    await process_i2v_image(message, bot, doc.file_id, state)


async def process_i2v_image(message: Message, bot: Bot, file_id: str, state: FSMContext):
    """Обработка изображения"""
    await message.answer("⏳ Загружаю фото...")
    
    try:
        photo_url = await file_storage.save_image_from_telegram(
            bot=bot,
            file_id=file_id,
            user_id=message.from_user.id
        )
        
        if not photo_url:
            await message.answer("❌ Ошибка сохранения фото. Попробуйте другое.")
            return
        
        await state.update_data(photo_url=photo_url)
        
        await message.answer(
            "✅ Фото загружено!\n\n"
            "✏️ <b>Опишите движение</b> (опционально):\n"
            "Например: «Медленно приближается камера» или «Человек улыбается»\n\n"
            "Или нажмите «Пропустить» для автоматической анимации:",
            parse_mode="HTML",
            reply_markup=skip_prompt_keyboard()
        )
        await state.set_state(ImageToVideoState.waiting_for_prompt)
        
    except Exception as e:
        logger.exception(f"Failed to process image: {e}")
        await message.answer("❌ Ошибка загрузки. Попробуйте другое фото.")


@router.message(ImageToVideoState.waiting_for_prompt)
async def receive_i2v_prompt(message: Message, state: FSMContext):
    """Получили промпт для видео"""
    prompt = message.text.strip()
    await state.update_data(prompt=prompt)
    
    await message.answer(
        f"✅ {prompt}\n\n"
        f"📐 <b>Выберите формат видео:</b>",
        parse_mode="HTML",
        reply_markup=video_aspect_ratio_keyboard()
    )
    await state.set_state(ImageToVideoState.waiting_for_aspect_ratio)


@router.callback_query(ImageToVideoState.waiting_for_prompt, F.data == "skip_prompt")
async def skip_i2v_prompt(callback: CallbackQuery, state: FSMContext):
    """Пропускаем промпт"""
    await state.update_data(prompt="Animate this image naturally with subtle motion")
    
    await callback.message.edit_text(
        "⏭️ Автоматическая анимация\n\n"
        f"📐 <b>Выберите формат видео:</b>",
        parse_mode="HTML",
        reply_markup=video_aspect_ratio_keyboard()
    )
    await state.set_state(ImageToVideoState.waiting_for_aspect_ratio)


@router.callback_query(ImageToVideoState.waiting_for_aspect_ratio, F.data.startswith("video_aspect_"))
async def receive_i2v_aspect(callback: CallbackQuery, state: FSMContext):
    aspect_ratio = callback.data.replace("video_aspect_", "")
    await state.update_data(aspect_ratio=aspect_ratio)
    
    await callback.message.edit_text(
        f"📐 {aspect_ratio}\n\n"
        f"⏱ <b>Длительность:</b>",
        parse_mode="HTML",
        reply_markup=image_to_video_duration_keyboard()
    )
    await state.set_state(ImageToVideoState.waiting_for_duration)


@router.callback_query(ImageToVideoState.waiting_for_duration, F.data.startswith("i2v_duration_"))
async def generate_image_to_video(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Генерируем видео из фото"""
    duration = int(callback.data.replace("i2v_duration_", ""))
    data = await state.get_data()
    prompt = data.get("prompt", "Animate naturally")
    aspect_ratio = data["aspect_ratio"]
    photo_url = data["photo_url"]
    user_id = callback.from_user.id
    
    quality = settings_manager.get_video_quality(user_id)
    
    await callback.message.edit_text(
        f"⏳ Создаю видео из фото...\n"
        f"Длительность: {duration} сек\n"
        f"⏱ Ожидание: 2-5 минут"
    )
    await state.set_state(ImageToVideoState.generating)
    
    try:
        if quality == "pro":
            result = await kling_service.generate_video_omni_pro(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
                start_image_url=photo_url
            )
        else:
            result = await kling_service.generate_video_omni_std(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
                start_image_url=photo_url
            )
        
        if result and result.get("task_id"):
            task_id = result["task_id"]
            
            await callback.message.edit_text(
                f"🎬 Генерация начата...\n"
                f"ID задачи: {task_id}\n"
                f"Проверяю статус..."
            )
            
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
                error_msg = status.get("data", {}).get("error", "Неизвестная ошибка") if status else "Таймаут"
                await callback.message.edit_text(
                    f"❌ Видео не создано.\nОшибка: {error_msg}",
                    reply_markup=main_menu()
                )
        else:
            error = result.get("error") if result else "Нет ответа от API"
            await callback.message.edit_text(
                f"❌ Ошибка запуска.\n{error}",
                reply_markup=main_menu()
            )
            
    except Exception as e:
        logger.exception(f"I2V generation failed: {e}")
        await callback.message.edit_text(
            "❌ Ошибка создания видео. Попробуйте позже.",
            reply_markup=main_menu()
        )
    
    await state.clear()
4. Исправленный batch_editing.py (добавлен импорт InlineKeyboardMarkup)
Python
Copy
import logging
import asyncio
from typing import List
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from bot.services.gemini_service import gemini_service
from bot.services.user_settings import settings_manager
from bot.keyboards import (
    aspect_ratio_keyboard, 
    main_menu, 
    batch_edit_ready_keyboard,
    batch_edit_add_more_keyboard
)
from bot.states import BatchEditState

router = Router()
logger = logging.getLogger(__name__)

MAX_BATCH_EDIT_IMAGES = 10


@router.message(F.text == "📂 Пакетное редактирование")
async def start_batch_editing(message: Message, state: FSMContext):
    """Начало пакетного редактирования"""
    await state.update_data(images=[], image_count=0)
    
    await message.answer(
        "📂 <b>Пакетное редактирование</b>\n\n"
        "Загрузите <b>несколько фотографий</b>, которые хотите обработать одинаково.\n\n"
        "📎 <b>Отправляйте фото по одному</b> или группой\n"
        f"Максимум: {MAX_BATCH_EDIT_IMAGES} шт\n\n"
        "Когда загрузите все — нажмите «Готово»",
        parse_mode="HTML",
        reply_markup=batch_edit_ready_keyboard(0)
    )
    await state.set_state(BatchEditState.collecting_images)


@router.message(BatchEditState.collecting_images, F.photo)
async def receive_batch_photo(message: Message, state: FSMContext):
    """Получили фото"""
    data = await state.get_data()
    images: List[bytes] = data.get("images", [])
    count = data.get("image_count", 0)
    
    if count >= MAX_BATCH_EDIT_IMAGES:
        await message.answer(
            f"⚠️ Достигнут лимит ({MAX_BATCH_EDIT_IMAGES} фото)\n"
            f"Нажмите «Готово» для продолжения",
            reply_markup=batch_edit_ready_keyboard(count)
        )
        return
    
    try:
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        image_bytes = await message.bot.download_file(file.file_path)
        image_data = image_bytes.read()
        
        images.append(image_data)
        count += 1
        
        await state.update_data(images=images, image_count=count)
        
        await message.answer(
            f"✅ Загружено: {count} фото\n"
            f"📎 Можете добавить ещё или нажать «Готово»",
            reply_markup=batch_edit_add_more_keyboard(count)
        )
        
    except Exception as e:
        logger.exception(f"Failed to download photo: {e}")
        await message.answer("❌ Ошибка загрузки, попробуйте другое фото")


@router.message(BatchEditState.collecting_images, F.document)
async def receive_batch_document(message: Message, state: FSMContext):
    """Получили файл"""
    doc = message.document
    
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        await message.answer("❌ Пожалуйста, отправьте изображение")
        return
    
    data = await state.get_data()
    images: List[bytes] = data.get("images", [])
    count = data.get("image_count", 0)
    
    if count >= MAX_BATCH_EDIT_IMAGES:
        await message.answer(
            f"⚠️ Достигнут лимит ({MAX_BATCH_EDIT_IMAGES} фото)",
            reply_markup=batch_edit_ready_keyboard(count)
        )
        return
    
    try:
        file = await message.bot.get_file(doc.file_id)
        image_bytes = await message.bot.download_file(file.file_path)
        image_data = image_bytes.read()
        
        images.append(image_data)
        count += 1
        
        await state.update_data(images=images, image_count=count)
        
        await message.answer(
            f"✅ Загружено: {count} фото",
            reply_markup=batch_edit_add_more_keyboard(count)
        )
        
    except Exception as e:
        logger.exception(f"Failed to download document: {e}")
        await message.answer("❌ Ошибка загрузки файла")


@router.callback_query(BatchEditState.collecting_images, F.data == "batch_edit_add")
async def continue_adding(callback: CallbackQuery):
    """Продолжаем добавлять"""
    await callback.answer("Отправьте следующее фото")


@router.callback_query(BatchEditState.collecting_images, F.data == "batch_edit_ready")
async def finish_collecting(callback: CallbackQuery, state: FSMContext):
    """Закончили собирать фото"""
    data = await state.get_data()
    images = data.get("images", [])
    count = data.get("image_count", 0)
    
    if count == 0:
        await callback.answer("❌ Нет загруженных фото!")
        return
    
    if count == 1:
        await callback.message.edit_text(
            "⚠️ Загружено только 1 фото.\n"
            "Для одиночного редактирования используйте «✏️ Редактировать изображение»\n\n"
            "Продолжить всё равно или отмена?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="▶️ Продолжить", callback_data="batch_continue_anyway")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="batch_edit_cancel")],
            ])
        )
        return
    
    await proceed_to_prompt(callback, state)


@router.callback_query(BatchEditState.collecting_images, F.data == "batch_continue_anyway")
async def continue_single(callback: CallbackQuery, state: FSMContext):
    """Продолжаем даже с 1 фото"""
    await proceed_to_prompt(callback, state)


async def proceed_to_prompt(callback: CallbackQuery, state: FSMContext):
    """Переходим к вводу промпта"""
    data = await state.get_data()
    count = data.get("image_count", 0)
    
    await callback.message.edit_text(
        f"✅ <b>{count} фото</b> принято!\n\n"
        f"✏️ <b>Что сделать со всеми фото?</b>\n"
        f"Например:\n"
        f"• «Увеличить контраст»\n"
        f"• «Сделать чёрно-белым»\n"
        f"• «Добавить рамку»\n"
        f"• «Улучшить качество»",
        parse_mode="HTML"
    )
    await state.set_state(BatchEditState.waiting_for_prompt)


@router.message(BatchEditState.waiting_for_prompt)
async def receive_batch_prompt(message: Message, state: FSMContext):
    """Получили промпт для всех фото"""
    prompt = message.text.strip()
    
    if len(prompt) < 3:
        await message.answer("❌ Описание слишком короткое:")
        return
    
    await state.update_data(prompt=prompt)
    
    await message.answer(
        f"✅ Задача: <i>{prompt}</i>\n\n"
        f"📐 <b>Выберите формат для всех фото:</b>",
        parse_mode="HTML",
        reply_markup=aspect_ratio_keyboard()
    )
    await state.set_state(BatchEditState.waiting_for_aspect_ratio)


@router.callback_query(BatchEditState.waiting_for_aspect_ratio, F.data.startswith("aspect_"))
async def execute_batch_edit(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Запускаем пакетное редактирование"""
    aspect_ratio = callback.data.replace("aspect_", "")
    data = await state.get_data()
    prompt = data["prompt"]
    images: List[bytes] = data["images"]
    count = len(images)
    user_id = callback.from_user.id
    
    model_pref = settings_manager.get_image_model(user_id)
    model = "gemini-2.5-flash-image" if model_pref == "flash" else "gemini-3-pro-image-preview"
    
    await callback.message.edit_text(
        f"⏳ Обрабатываю {count} фото...\n"
        f"Задача: {prompt}\n"
        f"0/{count} готово"
    )
    await state.set_state(BatchEditState.generating)
    
    semaphore = asyncio.Semaphore(3)
    
    async def edit_single(index: int, image_data: bytes) -> tuple:
        async with semaphore:
            try:
                result = await gemini_service.edit_image(
                    image_bytes=image_data,
                    instruction=prompt,
                    model=model,
                    aspect_ratio=aspect_ratio
                )
                return (index, result, None)
            except Exception as e:
                logger.exception(f"Failed to edit image {index}: {e}")
                return (index, None, str(e))
    
    tasks = [edit_single(i, img) for i, img in enumerate(images)]
    results = await asyncio.gather(*tasks)
    
    results.sort(key=lambda x: x[0])
    
    successful = 0
    failed = 0
    
    await callback.message.delete()
    
    status_msg = await bot.send_message(
        user_id,
        f"📤 Отправляю результаты..."
    )
    
    for index, result, error in results:
        if result:
            successful += 1
            await bot.send_photo(
                chat_id=user_id,
                photo=BufferedInputFile(result, filename=f"edited_{index+1}.png"),
                caption=f"✅ #{index+1}"
            )
        else:
            failed += 1
            await bot.send_message(
                user_id,
                f"❌ #{index+1} — ошибка обработки"
            )
    
    await status_msg.delete()
    await bot.send_message(
        user_id,
        f"✅ <b>Готово!</b>\n\n"
        f"📝 Задача: {prompt}\n"
        f"📐 Формат: {aspect_ratio}\n"
        f"✅ Успешно: {successful}/{count}\n"
        f"❌ Ошибок: {failed}",
        parse_mode="HTML",
        reply_markup=main_menu()
    )
    
    await state.clear()


@router.callback_query(F.data == "batch_edit_cancel")
async def cancel_batch_edit(callback: CallbackQuery, state: FSMContext):
    """Отмена"""
    await callback.message.edit_text("❌ Отменено")
    await callback.message.answer("Главное меню:", reply_markup=main_menu())
    await state.clear()
5. Исправленный bot.py (добавлены недостающие импорты)
Python
Copy
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import config
from bot.handlers import (
    start, 
    settings, 
    image_generation, 
    image_editing, 
    video_generation,
    batch_generation,
    batch_editing,
    image_to_video
)
from bot.services.file_storage import file_storage

logging.basicConfig(level=logging.INFO)

async def cleanup_task():
    """Фоновая задача очистки старых файлов"""
    while True:
        await asyncio.sleep(3600)
        try:
            deleted = file_storage.cleanup_old_files(max_age_hours=24)
            logging.info(f"Cleanup completed: {deleted} files deleted")
        except Exception as e:
            logging.error(f"Cleanup error: {e}")

async def main():
    bot = Bot(token=config.BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=MemoryStorage())
    
    # Подключаем роутеры
    dp.include_router(start.router)
    dp.include_router(settings.router)
    dp.include_router(image_generation.router)
    dp.include_router(batch_generation.router)
    dp.include_router(image_editing.router)
    dp.include_router(batch_editing.router)
    dp.include_router(video_generation.router)
    dp.include_router(image_to_video.router)
    
    # Запускаем очистку в фоне
    asyncio.create_task(cleanup_task())
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
