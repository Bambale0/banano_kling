import base64
import io
import logging
from typing import Any, Dict, List, Optional

import aiohttp
from PIL import Image

logger = logging.getLogger(__name__)


class GeminiService:
    """Сервис для работы с Nano Banana / OpenRouter Image Generation"""

    MODELS = {
        "flash": "google/gemini-2.0-flash-exp:free",  # Быстрая генерация (бесплатно)
        "pro": "google/gemini-2.5-pro-preview",  # Высокое качество
        "imagen": "google/imagen-3",  # Imagen 3
        "nano_flash": "gemini-2.5-flash-image",  # Native Nano Banana
        "nano_pro": "gemini-3-pro-image-preview",  # Native Nano Banana Pro
    }

    def __init__(
        self, api_key: str, nanobanana_key: str = "", openrouter_key: str = ""
    ):
        self.api_key = api_key  # Legacy Gemini key
        self.nanobanana_key = nanobanana_key
        self.openrouter_key = openrouter_key
        self._client = None
        self._session = None

    @property
    def client(self):
        """Ленивая инициализация клиента Google Genai (fallback)"""
        if self._client is None:
            try:
                from google import genai

                self._client = genai.Client(api_key=self.api_key)
            except ImportError:
                logger.warning("google-genai not installed. Using HTTP API.")
        return self._client

    async def _get_session(self) -> aiohttp.ClientSession:
        """Получение HTTP сессии"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def generate_via_nanobanana(
        self,
        prompt: str,
        model: str = "gemini-2.5-flash-image",
        image_input: Optional[bytes] = None,
    ) -> Optional[bytes]:
        """Генерация через Nano Banana API"""
        try:
            from bot.config import config

            session = await self._get_session()

            # Формируем контент
            contents = []

            # Если есть входное изображение
            if image_input:
                b64_image = base64.b64encode(image_input).decode("utf-8")
                contents.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64_image}"},
                    }
                )

            contents.append({"type": "text", "text": prompt})

            headers = {
                "Authorization": f"Bearer {self.nanobanana_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": model,
                "messages": [{"role": "user", "content": contents}],
                "max_tokens": 4096,
            }

            async with session.post(
                f"{config.NANOBANANA_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                if response.status == 200:
                    data = await response.json()

                    # Проверяем на изображение в ответе
                    if "choices" in data and len(data["choices"]) > 0:
                        message = data["choices"][0].get("message", {})

                        # Если есть изображение
                        if "image" in message:
                            b64_image = message["image"]
                            return base64.b64decode(b64_image)

                        # Если есть content с base64
                        content = message.get("content", "")
                        if content.startswith("data:image"):
                            # Извлекаем base64 из data URL
                            b64_data = content.split(",", 1)[1]
                            return base64.b64decode(b64_data)

                    logger.warning(f"Nano Banana response: {data}")
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Nano Banana API error: {response.status} - {error_text}"
                    )

            return None

        except Exception as e:
            logger.exception(f"Nano Banana generation failed: {e}")
            return None

    async def generate_via_openrouter(
        self,
        prompt: str,
        model: str = "google/gemini-2.0-flash-exp:free",
        image_input: Optional[bytes] = None,
    ) -> Optional[bytes]:
        """Генерация через OpenRouter API"""
        try:
            from bot.config import config

            session = await self._get_session()

            # Формируем контент
            contents = []

            # Если есть входное изображение
            if image_input:
                b64_image = base64.b64encode(image_input).decode("utf-8")
                contents.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64_image}"},
                    }
                )

            contents.append({"type": "text", "text": prompt})

            headers = {
                "Authorization": f"Bearer {self.openrouter_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://t.me/your_bot",  # Optional
                "X-Title": "Image Generation Bot",  # Optional
            }

            payload = {
                "model": model,
                "messages": [{"role": "user", "content": contents}],
            }

            async with session.post(
                f"{config.OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                if response.status == 200:
                    data = await response.json()

                    # OpenRouter возвращает текст или URL изображений
                    if "choices" in data and len(data["choices"]) > 0:
                        message = data["choices"][0].get("message", {})
                        content = message.get("content", "")

                        # Если вернулся URL изображения — скачиваем
                        if content and ("http" in content or "data:image" in content):
                            # Попытка найти URL в контенте
                            import re

                            url_match = re.search(
                                r'https?://[^\s"\']+\.(png|jpg|jpeg|webp)', content
                            )
                            if url_match:
                                img_url = url_match.group(0)
                                async with session.get(img_url) as img_response:
                                    if img_response.status == 200:
                                        return await img_response.read()

                            # Если data URL
                            if "data:image" in content:
                                b64_data = content.split(",", 1)[1]
                                return base64.b64decode(b64_data)

                    logger.info(f"OpenRouter response: {data}")
                else:
                    error_text = await response.text()
                    logger.error(
                        f"OpenRouter API error: {response.status} - {error_text}"
                    )

            return None

        except Exception as e:
            logger.exception(f"OpenRouter generation failed: {e}")
            return None

    async def generate_image(
        self,
        prompt: str,
        model: str = "gemini-2.5-flash-image",
        aspect_ratio: Optional[str] = None,
        image_input: Optional[bytes] = None,
    ) -> Optional[bytes]:
        """
        Генерация или редактирование изображения
        Приоритет: Nano Banana → OpenRouter → Native Gemini
        """

        # 1. Пробуем Nano Banana
        if self.nanobanana_key:
            result = await self.generate_via_nanobanana(prompt, model, image_input)
            if result:
                return result
            logger.info("Nano Banana failed, trying OpenRouter...")

        # 2. Пробуем OpenRouter
        if self.openrouter_key:
            # Маппинг модели для OpenRouter
            or_model = self.MODELS.get("flash", "google/gemini-2.0-flash-exp:free")
            if "pro" in model:
                or_model = self.MODELS.get("pro", "google/gemini-2.5-pro-preview")

            result = await self.generate_via_openrouter(prompt, or_model, image_input)
            if result:
                return result
            logger.info("OpenRouter failed, trying native Gemini...")

        # 3. Fallback на нативный Gemini API
        if self.api_key and self.client:
            try:
                from google.genai import types

                contents = [prompt]

                if image_input:
                    img = Image.open(io.BytesIO(image_input))
                    contents.append(img)

                config_params = types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"]
                )

                if aspect_ratio and "pro" in model:
                    config_params.image_config = types.ImageConfig(
                        aspect_ratio=aspect_ratio
                    )

                response = await self.client.models.generate_content_async(
                    model=model, contents=contents, config=config_params
                )

                for part in response.parts:
                    if part.inline_data:
                        logger.info(
                            f"Native Gemini image: {len(part.inline_data.data)} bytes"
                        )
                        return part.inline_data.data

            except ImportError as e:
                logger.error(f"Missing dependency: {e}")
            except Exception as e:
                logger.exception(f"Native Gemini generation failed: {e}")

        logger.warning("All image generation methods failed")
        return None

    async def generate_multi_turn(
        self, messages: List[Dict[str, Any]], model: str = "gemini-3-pro-image-preview"
    ) -> Optional[bytes]:
        """
        Многоходовое редактирование через чат (native Gemini only)
        """
        if not self.api_key or not self.client:
            logger.error("Multi-turn requires native Gemini API key")
            return None

        try:
            from google.genai import types

            chat = self.client.chats.create(
                model=model,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"]
                ),
            )

            response = None
            for msg in messages:
                response = await chat.send_message_async(msg["content"])

            if response:
                for part in response.parts:
                    if part.inline_data:
                        return part.inline_data.data
            return None

        except Exception as e:
            logger.exception(f"Multi-turn generation failed: {e}")
            return None

    async def edit_image(
        self,
        image_bytes: bytes,
        instruction: str,
        model: str = "gemini-2.5-flash-image",
    ) -> Optional[bytes]:
        """
        Упрощённый метод для редактирования изображения
        """
        return await self.generate_image(
            prompt=instruction, model=model, image_input=image_bytes
        )

    async def close(self):
        """Закрытие HTTP сессии"""
        if self._session and not self._session.closed:
            await self._session.close()


# Инициализация
from bot.config import config

gemini_service = GeminiService(
    api_key=config.GEMINI_API_KEY,
    nanobanana_key=config.NANOBANANA_API_KEY,
    openrouter_key=config.OPENROUTER_API_KEY,
)
