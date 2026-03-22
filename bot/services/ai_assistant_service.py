"""
AI Assistant Service - ИИ-ассистент для помощи пользователям
Использует OpenRouter (DeepSeek) как основной и Gemini/Kling как fallback
"""

import json
import logging
import os
from typing import Optional

import aiohttp

from bot.config import config

logger = logging.getLogger(__name__)

PRICE_FILE = os.path.join("data", "price.json")


def _load_price_data() -> dict:
    """Загрузить данные о ценах из data/price.json.
    Возвращает пустой словарь при ошибке - тогда будут использованы встроенные fallback-значения.
    """
    try:
        with open(PRICE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# Встроенные fallback-значения на случай отсутствия файла цен
FALLBACK_IMAGE_COSTS = {
    "novita": 3,
    "nanobanana": 3,
    "banana_pro": 5,
    "seedream": 3,
    "z_image_turbo": 3,
}

FALLBACK_VIDEO_COSTS = {
    "v3_std": 6,
    "v3_pro": 8,
    "v3_omni_std": 8,
    "v3_omni_pro": 8,
    "v3_omni_std_r2v": 8,
    "v3_omni_pro_r2v": 8,
    "v26_pro": 8,
    "v26_motion_pro": 10,
    "v26_motion_std": 8,
}


class AIAssistantService:
    """Сервис ИИ-ассистента для помощи пользователям с генерацией"""

    # Модели для ассистента (приоритет - быстрые и дешевые)
    MODELS = {
        "primary": "deepseek/deepseek-chat",  # Быстрый и умный
        "fallback": "google/gemini-2.5-flash",  # Fallback
    }

    def __init__(self):
        self._session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Получение HTTP сессии"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=60)  # 1 минута для ответов
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def get_assistant_response(
        self,
        user_message: str,
        context: dict = None,
    ) -> Optional[str]:
        """
        Получить ответ от ИИ-ассистента

        Args:
            user_message: Сообщение пользователя
            context: Дополнительный контекст (баланс, текущие настройки, история)

        Returns:
            Ответ ассистента или None при ошибке
        """
        # Загружаем системную инструкцию
        system_prompt = self._get_system_prompt()

        # Формируем контекст пользователя
        context_info = ""
        if context:
            context_info = self._format_context(context)

        # Получаем актуальные цены
        pricing_info = self.get_pricing_info()

        # Полное сообщение для модели
        full_message = f"""Контекст пользователя:
{context_info}

{pricing_info}

Вопрос пользователя: {user_message}"""

        # Пробуем через OpenRouter (DeepSeek)
        if config.OPENROUTER_API_KEY:
            result = await self._call_openrouter(
                system_prompt=system_prompt,
                user_message=full_message,
                model=self.MODELS["primary"],
            )
            if result:
                return result
            logger.info("DeepSeek failed, trying Gemini fallback...")

        # Fallback на Gemini через OpenRouter
        if config.OPENROUTER_API_KEY:
            result = await self._call_openrouter(
                system_prompt=system_prompt,
                user_message=full_message,
                model=self.MODELS["fallback"],
            )
            if result:
                return result

        logger.error("All AI assistant methods failed")
        return None

    async def _call_openrouter(
        self,
        system_prompt: str,
        user_message: str,
        model: str = "deepseek/deepseek-chat",
    ) -> Optional[str]:
        """Вызов OpenRouter API"""
        try:
            session = await self._get_session()

            headers = {
                "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://t.me/your_bot",
            }

            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "max_tokens": 1024,
                "temperature": 0.7,
            }

            async with session.post(
                f"{config.OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                if response.status == 200:
                    data = await response.json()

                    if "choices" in data and len(data["choices"]) > 0:
                        return data["choices"][0]["message"]["content"]

                error_text = await response.text()
                logger.error(f"OpenRouter API error: {response.status} - {error_text}")

            return None

        except Exception as e:
            logger.exception(f"OpenRouter call failed: {e}")
            return None

    def _get_system_prompt(self) -> str:
        """Загрузка системной инструкции из файла"""
        try:
            with open(
                "bot/utils/ai_assistant_instructions.json", "r", encoding="utf-8"
            ) as f:
                data = json.load(f)
                return data.get("system_prompt", "")
        except Exception as e:
            logger.warning(f"Failed to load AI instructions: {e}")
            return self._get_default_prompt()

    def _get_default_prompt(self) -> str:
        """Базовая системная инструкция если файл не найден"""
        return """Ты - дружелюбный ИИ-ассистент в боте для генерации изображений и видео.
Помогаешь пользователям:
1. Выбрать подходящую модель для генерации
2. Написать хороший промпт
3. Понять как редактировать фото
4. Выбрать настройки (формат, разрешение, качество)
5. Использовать различные функции бота

Отвечай кратко и по существу. Используй эмодзи для наглядности.
Если нужно что-то сделать в боте - подскажи какую кнопку нажать."""

    def _format_context(self, context: dict) -> str:
        """Форматирование контекста пользователя для ИИ"""
        lines = []

        if "user_credits" in context:
            lines.append(f"- Баланс: {context['user_credits']} бананов")

        if "preferred_model" in context:
            lines.append(f"- Текущая модель изображений: {context['preferred_model']}")

        if "preferred_video_model" in context:
            lines.append(f"- Текущая модель видео: {context['preferred_video_model']}")

        if "image_service" in context:
            service_names = {
                "nanobanana": "Nano Banana",
                "novita": "FLUX.2 Pro (Novita)",
                "banana_pro": "Banana Pro",
                "seedream": "Seedream (Novita)",
            }
            service = service_names.get(
                context["image_service"], context["image_service"]
            )
            lines.append(f"- Сервис изображений: {service}")

        return "\n".join(lines) if lines else "Нет дополнительного контекста"

    def get_pricing_info(self) -> str:
        """
        Получение актуальной информации о ценах для AI ассистента.
        Пытается загрузить цены из data/price.json и формирует читабельный блок с актуальными ценами.
        Если файл недоступен - используются встроенные fallback-значения.
        """
        price_data = _load_price_data()

        costs_ref = price_data.get("costs_reference", {}) if price_data else {}

        image_models = costs_ref.get("image_models", {}) or {}
        legacy = costs_ref.get("legacy_keys", {}) or {}

        # Resolve image costs with fallbacks
        def _img_cost(key, fallback_name=None):
            # Try exact key in image_models, then legacy, then fallback hardcoded
            if key in image_models:
                return image_models.get(key)
            if key in legacy:
                return legacy.get(key)
            # mapping for friendly names
            fbmap = {
                "novita": legacy.get("flux_pro") or image_models.get("flux_pro"),
                "nanobanana": image_models.get("banana_2")
                or legacy.get("gemini_2_5_flash"),
                "banana_pro": image_models.get("gemini_3_pro")
                or legacy.get("gemini_3_pro"),
                "seedream": image_models.get("seedream") or legacy.get("seedream"),
            }
            if (
                fallback_name
                and fallback_name in fbmap
                and fbmap[fallback_name] is not None
            ):
                return fbmap[fallback_name]
            return FALLBACK_IMAGE_COSTS.get(fallback_name or key, 3)

        novita_cost = _img_cost("flux_pro", "novita") or FALLBACK_IMAGE_COSTS["novita"]
        flash_cost = (
            _img_cost("banana_2", "nanobanana") or FALLBACK_IMAGE_COSTS["nanobanana"]
        )
        pro_cost = (
            _img_cost("gemini_3_pro", "banana_pro")
            or FALLBACK_IMAGE_COSTS["banana_pro"]
        )
        seedream_cost = (
            _img_cost("seedream", "seedream") or FALLBACK_IMAGE_COSTS["seedream"]
        )

        # Video models
        video_models = costs_ref.get("video_models", {}) or {}
        duration_table = costs_ref.get("video_duration_costs", {}) or {}

        def _video_cost(model_key, duration: int):
            # If model has explicit duration_costs, use it. Else use base * multiplier from duration_table
            model_info = video_models.get(model_key) or {}
            if model_info:
                dur_costs = model_info.get("duration_costs")
                if dur_costs and str(duration) in dur_costs:
                    return dur_costs[str(duration)]
                base = model_info.get("base") or model_info.get("cost")
                if base and str(duration) in duration_table:
                    return int(base) + int(duration_table.get(str(duration), 0))
                if base:
                    # fallback: scale linearly by 1x per 5 seconds
                    factor = max(1, duration // 5)
                    return int(base) * factor
            # last resort: try legacy keys
            legacy_val = legacy.get(model_key)
            if legacy_val:
                factor = max(1, duration // 5)
                return int(legacy_val) * factor
            # fallback default
            default_base = FALLBACK_VIDEO_COSTS.get(model_key, 8)
            factor = max(1, duration // 5)
            return int(default_base) * factor

        # Build common durations
        video_std_5 = _video_cost("v3_std", 5)
        video_std_10 = _video_cost("v3_std", 10)
        video_std_15 = _video_cost("v3_std", 15)

        video_pro_5 = _video_cost("v3_pro", 5)
        video_pro_10 = _video_cost("v3_pro", 10)
        # V2V (Video-to-Video)
        v2v_std_5 = _video_cost("v3_omni_std_r2v", 5)
        v2v_std_10 = _video_cost("v3_omni_std_r2v", 10)
        v2v_pro_5 = _video_cost("v3_omni_pro_r2v", 5)
        v2v_pro_10 = _video_cost("v3_omni_pro_r2v", 10)

        # Kling 2.6
        v26_5 = _video_cost("v26_pro", 5)
        v26_10 = _video_cost("v26_pro", 10)
        motion_pro_5 = _video_cost("v26_motion_pro", 5)
        motion_pro_10 = _video_cost("v26_motion_pro", 10)
        motion_std_5 = _video_cost("v26_motion_std", 5)
        motion_std_10 = _video_cost("v26_motion_std", 10)
        # Дополнительные расчёты для таблицы (некоторые модели имеют значения для 15 сек)
        video_pro_15 = _video_cost("v3_pro", 15)

        omni_std_5 = _video_cost("v3_omni_std", 5)
        omni_std_10 = _video_cost("v3_omni_std", 10)
        omni_std_15 = _video_cost("v3_omni_std", 15)

        omni_pro_5 = _video_cost("v3_omni_pro", 5)
        omni_pro_10 = _video_cost("v3_omni_pro", 10)
        omni_pro_15 = _video_cost("v3_omni_pro", 15)

        return f"""## АКТУАЛЬНЫЕ ЦЕНЫ (автоматически загружены из data/price.json)

🖼 Генерация изображений:
- FLUX.2 Pro (Novita): {novita_cost}🍌
- Nano Banana Flash: {flash_cost}🍌
- Nano Banana Pro: {pro_cost}🍌
- Seedream: {seedream_cost}🍌

🎬 Генерация видео (текст → видео):
│ Модель              │ 5 сек │ 10 сек │ 15 сек │
│ Kling 2.6           │ {v26_5}🍌   │ {v26_10}🍌  │  -     │
│ Kling 3 Std         │ {video_std_5}🍌   │ {video_std_10}🍌  │ {video_std_15}🍌  │
│ Kling 3 Pro         │ {video_pro_5}🍌   │ {video_pro_10}🍌  │ {video_pro_15}🍌  │
│ Kling 3 Omni Std    │ {omni_std_5}🍌   │ {omni_std_10}🍌  │ {omni_std_15}🍌  │
│ Kling 3 Omni Pro    │ {omni_pro_5}🍌   │ {omni_pro_10}🍌  │ {omni_pro_15}🍌  │

🎬 Kling 2.6 Motion Control (движение с видео):
│ Модель  │ 5 сек │ 10 сек │
│ Pro     │ {motion_pro_5}🍌   │ {motion_pro_10}🍌  │
│ Std     │ {motion_std_5}🍌   │ {motion_std_10}🍌  │

✂️ Видео-эффекты (видео → видео):
│ Модель  │ 5 сек │ 10 сек │
│ V2V Std │ {v2v_std_5}🍌   │ {v2v_std_10}🍌  │
│ V2V Pro │ {v2v_pro_5}🍌   │ {v2v_pro_10}🍌  │

✏️ Редактирование: {pro_cost}🍌"""

    async def close(self):
        """Закрытие сессии"""
        if self._session and not self._session.closed:
            await self._session.close()


# Инициализация сервиса
ai_assistant_service = AIAssistantService()
