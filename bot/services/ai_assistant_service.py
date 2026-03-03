"""
AI Assistant Service - ИИ-ассистент для помощи пользователям
Использует OpenRouter (DeepSeek) как основной и Gemini/Kling как fallback
"""
import json
import logging
from typing import Optional

import aiohttp

from bot.config import config
from bot.services.preset_manager import preset_manager

logger = logging.getLogger(__name__)


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

        if "menu_location" in context:
            lines.append(f"- Где находится пользователь: {context['menu_location']}")

        if "available_models" in context:
            lines.append(f"- Доступные модели: {context['available_models']}")

        return "\n".join(lines) if lines else "Нет дополнительного контекста"

    def get_pricing_info(self) -> str:
        """
        Получение актуальной информации о ценах для AI ассистента.
        Использует preset_manager для получения динамических цен.
        """
        try:
            # Получаем цены из preset_manager
            flash_cost = preset_manager.get_generation_cost("gemini-2.5-flash")
            pro_cost = preset_manager.get_generation_cost("gemini-3-pro-image-preview")
            novita_cost = preset_manager.get_generation_cost("z_image_turbo")
            seedream_cost = preset_manager.get_generation_cost("seedream")
            
            # Цены видео для разных длительностей
            video_std_5 = preset_manager.get_video_cost("v3_std", 5)
            video_std_10 = preset_manager.get_video_cost("v3_std", 10)
            video_std_15 = preset_manager.get_video_cost("v3_std", 15)
            
            video_pro_5 = preset_manager.get_video_cost("v3_pro", 5)
            video_pro_10 = preset_manager.get_video_cost("v3_pro", 10)
            video_pro_15 = preset_manager.get_video_cost("v3_pro", 15)
            
            omni_std_5 = preset_manager.get_video_cost("v3_omni_std", 5)
            omni_std_10 = preset_manager.get_video_cost("v3_omni_std", 10)
            omni_std_15 = preset_manager.get_video_cost("v3_omni_std", 15)
            
            omni_pro_5 = preset_manager.get_video_cost("v3_omni_pro", 5)
            omni_pro_10 = preset_manager.get_video_cost("v3_omni_pro", 10)
            omni_pro_15 = preset_manager.get_video_cost("v3_omni_pro", 15)
            
            # V2V (Video-to-Video) цены
            v2v_std_5 = preset_manager.get_video_cost("v3_omni_std_r2v", 5)
            v2v_std_10 = preset_manager.get_video_cost("v3_omni_std_r2v", 10)
            v2v_pro_5 = preset_manager.get_video_cost("v3_omni_pro_r2v", 5)
            v2v_pro_10 = preset_manager.get_video_cost("v3_omni_pro_r2v", 10)
            
            # Kling 2.6 цены
            v26_5 = preset_manager.get_video_cost("v26_pro", 5)
            v26_10 = preset_manager.get_video_cost("v26_pro", 10)
            motion_pro_5 = preset_manager.get_video_cost("v26_motion_pro", 5)
            motion_pro_10 = preset_manager.get_video_cost("v26_motion_pro", 10)
            motion_std_5 = preset_manager.get_video_cost("v26_motion_std", 5)
            motion_std_10 = preset_manager.get_video_cost("v26_motion_std", 10)
            
            return f"""## АКТУАЛЬНЫЕ ЦЕНЫ

🖼 Генерация изображений:
- FLUX.2 Pro (Novita): {novita_cost}🍌
- Nano Banana Flash: {flash_cost}🍌
- Nano Banana Pro: {pro_cost}🍌
- Seedream: {seedream_cost}🍌

🎬 Генерация видео (текст → видео):
┌─────────────────┬────────┬────────┬────────┐
│ Модель          │ 5 сек  │ 10 сек │ 15 сек │
├─────────────────┼────────┼────────┼────────┤
│ Kling 2.6       │ {v26_5}🍌   │ {v26_10}🍌   │   -   │
│ Kling 3 Std     │ {video_std_5}🍌   │ {video_std_10}🍌   │ {video_std_15}🍌   │
│ Kling 3 Pro     │ {video_pro_5}🍌   │ {video_pro_10}🍌  │ {video_pro_15}🍌  │
│ Kling 3 Omni Std│ {omni_std_5}🍌   │ {omni_std_10}🍌  │ {omni_std_15}🍌  │
│ Kling 3 Omni Pro│ {omni_pro_5}🍌   │ {omni_pro_10}🍌  │ {omni_pro_15}🍌  │
└─────────────────┴────────┴────────┴────────┘

🎬 Kling 2.6 Motion Control (движение с видео):
┌─────────────────┬────────┬────────┐
│ Модель          │ 5 сек  │ 10 сек │
├─────────────────┼────────┼────────┤
│ Pro             │ {motion_pro_5}🍌   │ {motion_pro_10}🍌   │
│ Std             │ {motion_std_5}🍌   │ {motion_std_10}🍌   │
└─────────────────┴────────┴────────┘

✂️ Видео-эффекты (видео → видео):
┌─────────────────┬────────┬────────┐
│ Модель          │ 5 сек  │ 10 сек │
├─────────────────┼────────┼────────┤
│ V2V Std         │ {v2v_std_5}🍌   │ {v2v_std_10}🍌   │
│ V2V Pro         │ {v2v_pro_5}🍌   │ {v2v_pro_10}🍌   │
└─────────────────┴────────┴────────┘

✏️ Редактирование: {pro_cost}🍌"""

        except Exception as e:
            logger.warning(f"Failed to get dynamic pricing: {e}")
            return """## ЦЕНЫ (уточняйте в боте)
- Генерация изображений: 3-5🍌
- Генерация видео: 6-16🍌
- Видео-эффекты: 8-14🍌
- Редактирование: 5🍌"""

    async def close(self):
        """Закрытие сессии"""
        if self._session and not self._session.closed:
            await self._session.close()


# Инициализация сервиса
ai_assistant_service = AIAssistantService()
