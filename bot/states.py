try:
    from vkbottle.dispatch.dispenser.base import BaseStateGroup
    from vkbottle.dispatch.dispenser.base import BaseStateGroup as StatesGroup
    from vkbottle.dispatch.dispenser.base import BaseStateGroup as _SG
    from vkbottle.dispatch.dispenser.base import State
except Exception:
    # Provide minimal shims for import-time; real vkbottle will supply runtime behavior
    class StatesGroup:
        pass

    class State:
        _counter = 0

        def __init__(self):
            self.value = f"state_{State._counter}"
            State._counter += 1


# Ensure State exists even when vkbottle provides BaseStateGroup but not a State helper
if "State" not in globals():

    class State:
        def __init__(self):
            pass


# String states for FSM (vkbottle uses strings)
UPLOADING_REFERENCE_IMAGES = "uploading_reference_images"
WAITING_FOR_INPUT = "waiting_for_input"
WAITING_FOR_IMAGE = "waiting_for_image"
WAITING_FOR_VIDEO = "waiting_for_video"
WAITING_FOR_VIDEO_PROMPT = "waiting_for_video_prompt"
WAITING_FOR_REFERENCE_VIDEO = "waiting_for_reference_video"
WAITING_FOR_VIDEO_START_IMAGE = "waiting_for_video_start_image"
CONFIRMING_GENERATION = "confirming_generation"
SELECTING_BATCH_COUNT = "selecting_batch_count"
CONFIRMING_REFERENCE_IMAGES = "confirming_reference_images"
WAITING_FOR_REFS = "waiting_for_refs"
WAITING_FOR_BATCH_IMAGE = "waiting_for_batch_image"
WAITING_FOR_BATCH_PROMPT = "waiting_for_batch_prompt"
WAITING_FOR_BATCH_ASPECT_RATIO = "waiting_for_batch_aspect_ratio"
SELECTING_DURATION = "selecting_duration"
SELECTING_ASPECT_RATIO = "selecting_aspect_ratio"
SELECTING_QUALITY = "selecting_quality"


class GenerationStates(StatesGroup):
    """Состояния для процесса генерации"""

    waiting_for_input = State()
    waiting_for_image = State()
    waiting_for_video = State()
    waiting_for_video_prompt = State()
    waiting_for_reference_video = State()
    waiting_for_video_start_image = State()
    confirming_generation = State()
    selecting_batch_count = State()

    # Состояния для загрузки референсных изображений (до 14 шт)
    uploading_reference_images = State()
    confirming_reference_images = State()

    # Состояния для пакетного редактирования
    waiting_for_refs = State()
    waiting_for_batch_image = State()
    waiting_for_batch_prompt = State()
    waiting_for_batch_aspect_ratio = State()

    # Состояния для видео-опций
    selecting_duration = State()
    selecting_aspect_ratio = State()
    selecting_quality = State()


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

    selecting_mode = State()  # Выбор режима: pro или standard
    selecting_preset = State()  # Выбор пресета
    entering_prompts = State()  # Ввод промптов (один или несколько)
    uploading_references = State()  # Загрузка референсных изображений
    confirming_batch = State()  # Подтверждение перед запуском
    selecting_batch_count = State()  # Количество изображений (для одиночного промпта)


class ImageAnalyzerStates(StatesGroup):
    """Состояния для анализа изображения в промпт"""

    waiting_for_photo = State()


class VideoCreationStates(StatesGroup):
    """Состояния для пошагового создания видео"""

    video_type_select = State()
    video_model_select = State()
    video_params_select = State()
    waiting_video_prompt = State()
