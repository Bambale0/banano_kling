"""Сервис AI-ассистента для пользовательских подсказок внутри бота."""

import json
import logging
import os
from typing import Optional

import aiohttp

from bot.config import config

logger = logging.getLogger(__name__)

PRICE_FILE = os.path.join("data", "price.json")
AI_INSTRUCTIONS_FILE = os.path.join("bot", "utils", "ai_assistant_instructions.json")

# Fallback-цены на случай, если data/price.json недоступен.
FALLBACK_IMAGE_COSTS = {
    "banana_pro": 2.5,
    "banana_2": 2.5,
    "seedream_edit": 1.5,
    "grok_imagine_i2i": 3,
}

FALLBACK_VIDEO_COSTS = {
    "v3_std": 15,
    "v3_pro": 15,
    "v26_pro": 15,
    "v26_motion_pro": 15,
    "v26_motion_std": 15,
    "grok_imagine": 15,
    "glow": 25,
    "veo3": 22,
    "veo3_fast": 15,
    "veo3_lite": 10,
}

IMAGE_SERVICE_LABELS = {
    "banana_pro": "Banana Pro",
    "banana_2": "Banana 2",
    "nanobanana": "Banana 2",
    "seedream": "Seedream",
    "seedream_edit": "Seedream 4.5",
    "grok_imagine_i2i": "Grok Imagine i2i",
}


def _load_json(path: str) -> dict:
    """Загрузить JSON-файл. При ошибке вернуть пустой словарь."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


class AIAssistantService:
    """Сервис AI-ассистента для помощи с моделями, промптами и настройками."""

    ENDPOINT = "/gpt-5-2/v1/chat/completions"

    def __init__(self):
        self._session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Получение HTTP-сессии."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=60)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def get_assistant_response(
        self,
        user_message: str,
        context: dict = None,
    ) -> Optional[str]:
        """Получить ответ от AI-ассистента."""
        if not config.KIE_AI_API_KEY:
            logger.error("Kie.ai API key not configured for AI Assistant")
            return None

        system_prompt = self._get_system_prompt()
        context_info = self._format_context(context or {})
        pricing_info = self.get_pricing_info()

        full_message = f"""Контекст пользователя:
{context_info}

{pricing_info}

Вопрос пользователя: {user_message}"""

        try:
            session = await self._get_session()
            headers = {
                "Authorization": f"Bearer {config.KIE_AI_API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "messages": [
                    {
                        "role": "developer",
                        "content": [{"type": "text", "text": system_prompt}],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": full_message}],
                    },
                ],
                "tools": [{"type": "function", "function": {"name": "web_search"}}],
                "stream": False,
                "reasoning_effort": "high",
            }

            async with session.post(
                f"{config.KIE_BASE_URL}{self.ENDPOINT}",
                headers=headers,
                json=payload,
            ) as response:
                response_text = await response.text()
                logger.info(
                    "Kie.ai GPT 5.2 response status: %s, content-type: %s",
                    response.status,
                    response.headers.get("content-type", "none"),
                )
                logger.info("Response preview: %s...", response_text[:500])

                if response.status != 200:
                    logger.error(
                        "Kie.ai GPT 5.2 error %s: %s",
                        response.status,
                        response_text[:1000],
                    )
                    return None

                try:
                    data = json.loads(response_text)
                except json.JSONDecodeError as json_err:
                    logger.error(
                        "JSON decode error: %s. Raw response: %s",
                        json_err,
                        response_text[:1000],
                    )
                    return None

                choices = data.get("choices") or []
                if choices:
                    return choices[0].get("message", {}).get("content")
                return None

        except Exception as e:
            logger.exception(f"Kie.ai GPT 5.2 call failed: {e}")
            return None

    def _get_system_prompt(self) -> str:
        """Загрузка системной инструкции из JSON-файла."""
        try:
            data = _load_json(AI_INSTRUCTIONS_FILE)
            return data.get("system_prompt") or self._get_default_prompt()
        except Exception as e:
            logger.warning(f"Failed to load AI instructions: {e}")
            return self._get_default_prompt()

    def _get_default_prompt(self) -> str:
        """Базовая системная инструкция, если файл с инструкциями недоступен."""
        return """Ты — AI-ассистент в Telegram-боте для генерации изображений и видео.
Помогай пользователю:
1. выбирать подходящую модель;
2. писать более сильные промпты;
3. понимать, когда нужны референсы;
4. подбирать формат, длительность и режим генерации;
5. ориентироваться в возможностях бота.

Отвечай кратко, дружелюбно и прикладно.
Если это помогает, подсказывай конкретный следующий шаг в интерфейсе бота."""

    def _format_context(self, context: dict) -> str:
        """Форматирование контекста пользователя для AI-ассистента."""
        lines = []

        if "user_credits" in context:
            lines.append(f"- Баланс: {context['user_credits']} бананов")

        if "preferred_model" in context:
            lines.append(f"- Текущая модель изображений: {context['preferred_model']}")

        if "preferred_video_model" in context:
            lines.append(f"- Текущая модель видео: {context['preferred_video_model']}")

        if "image_service" in context:
            service = IMAGE_SERVICE_LABELS.get(
                context["image_service"], context["image_service"]
            )
            lines.append(f"- Сервис изображений: {service}")

        if "menu_location" in context:
            lines.append(f"- Раздел бота: {context['menu_location']}")

        if "available_models" in context:
            lines.append(f"- Доступные модели: {context['available_models']}")

        return "\n".join(lines) if lines else "Нет дополнительного контекста"

    def get_pricing_info(self) -> str:
        """Собрать краткий блок с актуальными ценами для AI-ассистента."""
        price_data = _load_json(PRICE_FILE)
        costs_ref = price_data.get("costs_reference", {}) if price_data else {}
        image_models = costs_ref.get("image_models", {}) or {}
        video_models = costs_ref.get("video_models", {}) or {}
        duration_table = costs_ref.get("video_duration_costs", {}) or {}
        legacy = costs_ref.get("legacy_keys", {}) or {}

        def _resolve_image_cost(*keys: str, fallback: int) -> int:
            for key in keys:
                value = image_models.get(key)
                if value is not None:
                    return int(value)
                value = legacy.get(key)
                if value is not None:
                    return int(value)
            return fallback

        def _resolve_video_cost(model_key: str, duration: int) -> int:
            model_info = video_models.get(model_key) or {}
            if model_info:
                dur_costs = model_info.get("duration_costs") or {}
                if str(duration) in dur_costs:
                    return int(dur_costs[str(duration)])
                base = model_info.get("base") or model_info.get("cost")
                if base is not None:
                    if str(duration) in duration_table:
                        return int(base) + int(duration_table[str(duration)])
                    factor = max(1, duration // 5)
                    return int(base) * factor

            legacy_value = legacy.get(model_key)
            if legacy_value is not None:
                factor = max(1, duration // 5)
                return int(legacy_value) * factor

            base = FALLBACK_VIDEO_COSTS.get(model_key, 8)
            factor = max(1, duration // 5)
            return int(base) * factor

        banana_pro_cost = _resolve_image_cost(
            "banana_pro",
            "nano-banana-pro",
            "gemini_3_pro",
            fallback=FALLBACK_IMAGE_COSTS["banana_pro"],
        )
        banana_2_cost = _resolve_image_cost(
            "banana_2",
            "gemini_2_5_flash",
            fallback=FALLBACK_IMAGE_COSTS["banana_2"],
        )
        seedream_cost = _resolve_image_cost(
            "seedream_edit",
            "seedream_45",
            "seedream",
            fallback=FALLBACK_IMAGE_COSTS["seedream_edit"],
        )
        grok_i2i_cost = _resolve_image_cost(
            "grok_imagine_i2i",
            fallback=FALLBACK_IMAGE_COSTS["grok_imagine_i2i"],
        )

        kling_std_5 = _resolve_video_cost("v3_std", 5)
        kling_std_10 = _resolve_video_cost("v3_std", 10)
        kling_std_15 = _resolve_video_cost("v3_std", 15)
        kling_pro_5 = _resolve_video_cost("v3_pro", 5)
        kling_pro_10 = _resolve_video_cost("v3_pro", 10)
        kling_pro_15 = _resolve_video_cost("v3_pro", 15)
        kling26_5 = _resolve_video_cost("v26_pro", 5)
        kling26_10 = _resolve_video_cost("v26_pro", 10)
        grok_6 = _resolve_video_cost("grok_imagine", 6)
        grok_10 = _resolve_video_cost("grok_imagine", 10)
        grok_20 = _resolve_video_cost("grok_imagine", 20)
        grok_30 = _resolve_video_cost("grok_imagine", 30)
        glow_5 = _resolve_video_cost("glow", 5)
        glow_10 = _resolve_video_cost("glow", 10)
        veo_quality = _resolve_video_cost("veo3", 5)
        veo_fast = _resolve_video_cost("veo3_fast", 5)
        veo_lite = _resolve_video_cost("veo3_lite", 5)
        motion_pro_5 = _resolve_video_cost("v26_motion_pro", 5)
        motion_pro_10 = _resolve_video_cost("v26_motion_pro", 10)
        motion_std_5 = _resolve_video_cost("v26_motion_std", 5)
        motion_std_10 = _resolve_video_cost("v26_motion_std", 10)

        return f"""## АКТУАЛЬНЫЕ ЦЕНЫ

🖼 Генерация изображений:
- Banana Pro: {banana_pro_cost}🍌
- Banana 2: {banana_2_cost}🍌
- Seedream / Seedream 4.5: {seedream_cost}🍌
- Grok Imagine i2i: {grok_i2i_cost}🍌

🎬 Генерация видео:
- Kling 3 Std: {kling_std_5}🍌 / {kling_std_10}🍌 / {kling_std_15}🍌 за 5/10/15 сек
- Kling 3 Pro: {kling_pro_5}🍌 / {kling_pro_10}🍌 / {kling_pro_15}🍌 за 5/10/15 сек
- Kling 2.6: {kling26_5}🍌 / {kling26_10}🍌 за 5/10 сек
- Grok Imagine: {grok_6}🍌 / {grok_10}🍌 / {grok_20}🍌 / {grok_30}🍌 за 6/10/20/30 сек
- Glow: {glow_5}🍌 / {glow_10}🍌 за 5/10 сек
- Veo 3.1 Quality: {veo_quality}🍌
- Veo 3.1 Fast: {veo_fast}🍌
- Veo 3.1 Lite: {veo_lite}🍌

🎯 Motion Control:
- Pro: {motion_pro_5}🍌 / {motion_pro_10}🍌 за 5/10 сек
- Std: {motion_std_5}🍌 / {motion_std_10}🍌 за 5/10 сек

✏️ Редактирование фото: от {banana_pro_cost}🍌"""

    async def close(self):
        """Закрытие HTTP-сессии."""
        if self._session and not self._session.closed:
            await self._session.close()


ai_assistant_service = AIAssistantService()
