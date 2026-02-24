from aiogram.fsm.state import State, StatesGroup


class GenerationStates(StatesGroup):
    """Состояния для процесса генерации"""

    waiting_for_input = State()  # Ожидание пользовательского ввода
    waiting_for_image = State()  # Ожидание загрузки фото
    waiting_for_video = State()  # Ожидание загрузки видео
    confirming_generation = State()  # Подтверждение перед запуском
    selecting_batch_count = (
        State()
    )  # Выбор количества изображений для пакетной генерации
    
    # Состояния для видео-опций
    selecting_duration = State()  # Выбор длительности видео
    selecting_aspect_ratio = State()  # Выбор формата видео
    selecting_quality = State()  # Выбор качества видео


class PaymentStates(StatesGroup):
    """Состояния для процесса оплаты"""

    selecting_package = State()  # Выбор пакета
    confirming_payment = State()  # Подтверждение оплаты
    waiting_payment = State()  # Ожидание оплаты


class AdminStates(StatesGroup):
    """Состояния для админ-панели"""

    waiting_broadcast_text = State()  # Ввод текста рассылки
    confirming_broadcast = State()  # Подтверждение рассылки
    waiting_user_id = State()  # Ввод ID пользователя
    waiting_credits_amount = State()  # Ввод количества кредитов


class BatchGenerationStates(StatesGroup):
    """Состояния для пакетной генерации"""
    
    selecting_mode = State()           # Выбор режима: pro или standard
    selecting_preset = State()         # Выбор пресета
    entering_prompts = State()         # Ввод промптов (один или несколько)
    uploading_references = State()     # Загрузка референсных изображений
    confirming_batch = State()         # Подтверждение перед запуском
    selecting_batch_count = State()    # Количество изображений (для одиночного промпта)


# =============================================================================
# НОВЫЕ УПРОЩЁННЫЕ СОСТОЯНИЯ (ДЛЯ НОВОГО UX)
# =============================================================================

class ImageGenState(StatesGroup):
    """Упрощённая генерация изображений"""
    waiting_for_prompt = State()
    waiting_for_aspect_ratio = State()
    generating = State()


class ImageEditState(StatesGroup):
    """Упрощённое редактирование изображений"""
    waiting_for_image = State()
    waiting_for_prompt = State()
    waiting_for_aspect_ratio = State()
    generating = State()


class VideoGenState(StatesGroup):
    """Упрощённая генерация видео"""
    waiting_for_prompt = State()
    waiting_for_aspect_ratio = State()
    waiting_for_duration = State()
    generating = State()


class SettingsState(StatesGroup):
    """Настройки пользователя"""
    main = State()
    selecting_model = State()
    selecting_video_quality = State()
