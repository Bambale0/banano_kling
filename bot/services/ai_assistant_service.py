"""
AI Assistant Service - ИИ-ассистент для помощи пользователям
Использует OpenRouter (DeepSeek) как основной и Gemini/Kling как fallback
"""
import json
import logging
from typing import Optional

import aiohttp

from bot.config import config

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

        # Полное сообщение для модели
        full_message = f"""Контекст пользователя:
{context_info}

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

    async def close(self):
        """Закрытие сессии"""
        if self._session and not self._session.closed:
            await self._session.close()


# Инициализация сервиса
ai_assistant_service = AIAssistantService()
