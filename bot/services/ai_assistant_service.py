"""
AI Assistant Service - ИИ-ассистент для помощи пользователям (Kie.ai GPT 5.2)
"""

import json
import logging
import os
from typing import Optional

import aiohttp

from bot.config import config

logger = logging.getLogger(__name__)

PRICE_FILE = os.path.join("data", "price.json")


def load_prices():
    """Загружает цены из price.json (как в keyboards.py)"""
    price_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "price.json"
    )
    try:
        with open(price_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Fallback как в keyboards.py
        return {
            "costs_reference": {
                "image_models": {
                    "flux_pro": 3,
                    "nanobanana": 3,
                    "banana_pro": 5,
                    "seedream": 3,
                },
                "video_models": {
                    "v26_pro": {"base": 8, "duration_costs": {"5": 8, "10": 14}},
                    "v3_std": {
                        "base": 6,
                        "duration_costs": {"5": 6, "10": 8, "15": 10},
                    },
                    "v3_pro": {
                        "base": 8,
                        "duration_costs": {"5": 8, "10": 14, "15": 16},
                    },
                    "v3_omni_std": {
                        "base": 8,
                        "duration_costs": {"5": 8, "10": 14, "15": 16},
                    },
                    "v3_omni_pro": {
                        "base": 8,
                        "duration_costs": {"5": 8, "10": 14, "15": 16},
                    },
                },
            },
            "packages": [
                {"id": "mini", "credits": 15, "price_rub": 150},
                {"id": "standard", "credits": 30, "price_rub": 250},
                {"id": "optimal", "credits": 50, "price_rub": 400, "popular": True},
                {"id": "pro", "credits": 100, "price_rub": 700},
            ],
        }


PRICES = load_prices()

IMAGE_COSTS = PRICES.get("costs_reference", {}).get("image_models", {})
VIDEO_COSTS = PRICES.get("costs_reference", {}).get("video_models", {})


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
    """Сервис ИИ-ассистента для помощи пользователям с генерацией (Kie.ai GPT 5.2)"""

    ENDPOINT = "/gpt-5-2/v1/chat/completions"

    def __init__(self):
        self._session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Получение HTTP сессии"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=60)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def get_assistant_response(
        self,
        user_message: str,
        context: dict = None,
        history: list = None,
    ) -> Optional[str]:
        """
        Получить ответ от ИИ-ассистента с поддержкой истории (до 7 сообщений)

        Args:
            user_message: Сообщение пользователя
            context: Дополнительный контекст
            history: Список предыдущих сообщений [{"role": "user/assistant", "content": str}]

        Returns:
            Ответ ассистента или None
        """
        if not config.KIE_AI_API_KEY:
            logger.error("Kie.ai API key not configured for AI Assistant")
            return None

        system_prompt = self._get_system_prompt()

        context_info = self._format_context(context) if context else ""
        pricing_info = self.get_pricing_info()

        # Строим messages: system + history (max 6 prev) + current user
        messages = [
            {"role": "system", "content": [{"type": "text", "text": system_prompt}]}
        ]

        if history:
            # Берем последние 6 сообщений (3 пары user-assistant)
            recent_history = history[-6:]
            messages.extend(
                [
                    {
                        "role": msg["role"],
                        "content": [{"type": "text", "text": msg["content"]}],
                    }
                    for msg in recent_history
                ]
            )

        # Текущий user message с контекстом и ценами
        current_user = f"""Контекст: {context_info}

Цены: {pricing_info}

Сообщение: {user_message}"""
        messages.append(
            {"role": "user", "content": [{"type": "text", "text": current_user}]}
        )

        try:
            session = await self._get_session()

            headers = {
                "Authorization": f"Bearer {config.KIE_AI_API_KEY}",
                "Content-Type": "application/json",
            }

            payload = {
                "messages": messages,
                "tools": [{"type": "function", "function": {"name": "web_search"}}],
                "reasoning_effort": "high",
            }

            async with session.post(
                f"{config.KIE_BASE_URL}{self.ENDPOINT}",
                headers=headers,
                json=payload,
            ) as response:
                text = await response.text()
                if response.status == 200:
                    try:
                        data = json.loads(text)
                        if "choices" in data and data["choices"]:
                            content = (
                                data["choices"][0].get("message", {}).get("content")
                            )
                            if content:
                                return content
                    except json.JSONDecodeError as e:
                        logger.error(f"JSON decode error in Kie.ai response: {e}")
                        logger.error(f"Response text (first 1000 chars): {text[:1000]}")
                else:
                    logger.error(f"Kie.ai GPT 5.2 HTTP {response.status}: {text[:500]}")
                logger.error(
                    f"Kie.ai GPT 5.2 call failed: status={response.status}, text preview: {text[:200]}"
                )
            return None

        except Exception as e:
            logger.exception(f"Kie.ai GPT 5.2 call failed: {e}")
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
            lines.append(f"- Баланс: {context['user_credits']} GOEов")

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
        """Динамическая таблица цен из PRICES (как в keyboards.py)"""
        image_costs = IMAGE_COSTS
        video_costs = VIDEO_COSTS

        # Image models from keyboards.py and price.json
        img_prices = {}
        for model, cost in image_costs.items():
            if isinstance(cost, (int, float)):
                img_prices[model] = int(cost)
            else:
                img_prices[model] = list(cost.values())[0] if cost else 3

        # Key image models
        banana_pro = img_prices.get("banana_pro", 5)
        banana_2 = img_prices.get("banana_2", 7)
        seedream_5_lite = img_prices.get("seedream_5_lite", 6)
        seedream_edit = img_prices.get("seedream_edit", 7)

        # Video costs for 5s
        v3_std_5 = VIDEO_COSTS.get("v3_std", {}).get("duration_costs", {}).get("5", 15)
        v3_pro_5 = VIDEO_COSTS.get("v3_pro", {}).get("duration_costs", {}).get("5", 15)
        seedance2_5 = (
            VIDEO_COSTS.get("seedance2", {}).get("duration_costs", {}).get("5", 15)
        )
        runway_5 = VIDEO_COSTS.get("runway", {}).get("duration_costs", {}).get("5", 15)
        grok_6 = (
            VIDEO_COSTS.get("grok_imagine", {}).get("duration_costs", {}).get("6", 15)
        )
        aleph_5 = VIDEO_COSTS.get("aleph", {}).get("duration_costs", {}).get("5", 15)
        glow_5 = VIDEO_COSTS.get("glow", {}).get("duration_costs", {}).get("5", 25)

        return f"""💎 АКТУАЛЬНЫЕ ЦЕНЫ (из data/price.json)

🖼️ ИЗОБРАЖЕНИЯ (1 шт):
• Banana Pro: {banana_pro}💎
• Banana 2: {banana_2}💎
• Seedream 5.0 Lite: {seedream_5_lite}💎
• Seedream Edit: {seedream_edit}💎

🎬 ВИДЕО (текст→видео, 5 сек):
• Kling 3 Std: {v3_std_5}💎
• Kling 3 Pro: {v3_pro_5}💎
• Seedance 2.0: {seedance2_5}💎 (img+txt)
• Runway AI: {runway_5}💎
• Grok Imagine: {grok_6}💎 (6 сек)
• Aleph/Glow (video ref): {aleph_5}/{glow_5}💎

📱 Motion Control (5 сек): 15-25💎
📸 Photo→Prompt: бесплатно

Пакеты: 15💎/150₽, 30/250₽, 50/400₽🔥, 100/700₽, 200/1400₽"""

    async def close(self):
        """Закрытие сессии"""
        if self._session and not self._session.closed:
            await self._session.close()


# Инициализация сервиса
ai_assistant_service = AIAssistantService()
