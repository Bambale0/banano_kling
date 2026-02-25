import base64
import io
import logging
from typing import Any, Dict, List, Optional, Union

import aiohttp
from PIL import Image

logger = logging.getLogger(__name__)


class GeminiService:
    """Сервис для работы с Nano Banana / Gemini Image Generation API"""

    # Модели согласно banana_api.md
    # OpenRouter model IDs
    MODELS = {
        "flash": "google/gemini-2.5-flash-image",  # Быстрая генерация
        "pro": "google/gemini-3-pro-image-preview",  # Профессиональная, до 4K, с thinking
    }

    # Native Gemini model names (for direct API calls)
    NATIVE_MODELS = {
        "flash": "gemini-2.5-flash-image",
        "pro": "gemini-3-pro-image-preview",
    }

    # Поддерживаемые разрешения (согласно banana_api.md)
    RESOLUTIONS = {
        "1K": "1K",  # 1024px (по умолчанию)
        "2K": "2K",  # 2048px
        "4K": "4K",  # 4096px
    }

    # Поддерживаемые форматы (согласно banana_api.md)
    ASPECT_RATIOS = [
        "1:1",
        "2:3",
        "3:2",
        "3:4",
        "4:3",
        "4:5",
        "5:4",
        "9:16",
        "16:9",
        "21:9",
    ]

    def __init__(
        self, api_key: str, nanobanana_key: str = "", openrouter_key: str = ""
    ):
        self.api_key = api_key  # Legacy Gemini key
        self.nanobanana_key = nanobanana_key
        self.openrouter_key = openrouter_key
        self._client = None
        self._session = None
        self._chats = {}  # Для многоходового редактирования

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

    # =========================================================================
    # ОСНОВНЫЕ МЕТОДЫ ГЕНЕРАЦИИ (согласно banana_api.md)
    # =========================================================================

    async def generate_image(
        self,
        prompt: str,
        model: str = "gemini-2.5-flash-image",
        aspect_ratio: Optional[str] = None,
        image_input: Optional[bytes] = None,
        image_input_url: Optional[str] = None,
        resolution: str = "1K",
        enable_search: bool = False,
        reference_images: List[bytes] = None,
        reference_image_urls: List[str] = None,
    ) -> Optional[bytes]:
        """
        Основной метод генерации изображения
        Поддерживает все возможности из banana_api.md:
        - Text-to-image
        - Image-to-image (редактирование)
        - До 14 референсных изображений
        - Grounding с Google Search
        - Разрешение до 4K
        """
        # 1. Пробуем Nano Banana
        if self.nanobanana_key:
            result = await self._generate_via_nanobanana(
                prompt=prompt,
                model=model,
                image_input=image_input,
                image_input_url=image_input_url,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                enable_search=enable_search,
                reference_images=reference_images,
                reference_image_urls=reference_image_urls,
            )
            if result:
                return result
            logger.info("Nano Banana failed, trying OpenRouter...")

        # 2. Пробуем OpenRouter
        if self.openrouter_key:
            # Determine which OpenRouter model to use based on the requested model
            or_model = self.MODELS.get("flash")  # Default to flash
            if "pro" in model.lower():
                or_model = self.MODELS.get("pro")  # Use pro model

            result = await self._generate_via_openrouter(
                prompt=prompt,
                model=or_model,
                image_input=image_input,
                image_input_url=image_input_url,
                aspect_ratio=aspect_ratio,
                reference_images=reference_images,
                reference_image_urls=reference_image_urls,
            )
            if result:
                return result
            logger.info("OpenRouter failed, trying native Gemini...")

        # 3. Fallback на нативный Gemini API
        if self.api_key and self.client:
            return await self._generate_via_native_gemini(
                prompt=prompt,
                model=model,
                image_input=image_input,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                enable_search=enable_search,
                reference_images=reference_images,
            )

        logger.warning("All image generation methods failed")
        return None

    async def _generate_via_nanobanana(
        self,
        prompt: str,
        model: str = "gemini-2.5-flash-image",
        image_input: Optional[bytes] = None,
        image_input_url: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        resolution: str = "1K",
        enable_search: bool = False,
        reference_images: List[bytes] = None,
        reference_image_urls: List[str] = None,
    ) -> Optional[bytes]:
        """Генерация через Nano Banana API"""
        try:
            from bot.config import config

            session = await self._get_session()

            # Формируем контент
            contents = []

            # Добавляем референсные изображения по URL (приоритет)
            if reference_image_urls:
                for img_url in reference_image_urls[:14]:  # Ограничение до 14
                    contents.append(
                        {"type": "image_url", "image_url": {"url": img_url}}
                    )
            # Fallback на bytes
            elif reference_images:
                for ref_img in reference_images[:14]:  # Ограничение до 14
                    b64_image = base64.b64encode(ref_img).decode("utf-8")
                    contents.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64_image}"},
                        }
                    )

            # Если есть входное изображение по URL (приоритет)
            if image_input_url:
                contents.append(
                    {"type": "image_url", "image_url": {"url": image_input_url}}
                )
            # Fallback на bytes
            elif image_input:
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

            # Формируем payload согласно banana_api.md
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": contents}],
                "max_tokens": 4096,
            }

            # Добавляем image_config если указан
            if aspect_ratio or resolution != "1K":
                payload["generationConfig"] = {}
                if aspect_ratio:
                    payload["generationConfig"]["aspectRatio"] = aspect_ratio
                if resolution != "1K":
                    payload["generationConfig"]["imageSize"] = resolution

            # Добавляем tools для search grounding
            if enable_search:
                if "generationConfig" not in payload:
                    payload["generationConfig"] = {}
                payload["generationConfig"]["tools"] = [{"google_search": {}}]

            async with session.post(
                f"{config.NANOBANANA_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                if response.status == 200:
                    data = await response.json()

                    if "choices" in data and len(data["choices"]) > 0:
                        message = data["choices"][0].get("message", {})

                        if "image" in message:
                            b64_image = message["image"]
                            return base64.b64decode(b64_image)

                        content = message.get("content", "")
                        if content.startswith("data:image"):
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

    async def _generate_via_openrouter(
        self,
        prompt: str,
        model: str = "google/gemini-2.0-flash-exp:free",
        image_input: Optional[bytes] = None,
        image_input_url: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        reference_images: List[bytes] = None,
        reference_image_urls: List[str] = None,
    ) -> Optional[bytes]:
        """Генерация через OpenRouter API"""
        try:
            import json
            import re

            from bot.config import config

            session = await self._get_session()

            contents = []

            # Референсные изображения по URL (приоритет)
            if reference_image_urls:
                for img_url in reference_image_urls[:5]:  # OpenRouter ограничение
                    contents.append(
                        {"type": "image_url", "image_url": {"url": img_url}}
                    )
            # Fallback на bytes
            elif reference_images:
                for ref_img in reference_images[:5]:  # OpenRouter ограничение
                    b64_image = base64.b64encode(ref_img).decode("utf-8")
                    contents.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64_image}"},
                        }
                    )

            # Входное изображение по URL (приоритет)
            if image_input_url:
                contents.append(
                    {"type": "image_url", "image_url": {"url": image_input_url}}
                )
            # Fallback на bytes
            elif image_input:
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
                "HTTP-Referer": "https://t.me/your_bot ",
                "X-Title": "Image Generation Bot",
            }

            # Добавляем modalities для генерации изображений согласно документации OpenRouter
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": contents}],
                "modalities": ["image", "text"],
            }

            # Добавляем aspect_ratio в промпт (OpenRouter/Gemini лучше понимает через текст)
            final_prompt = prompt
            if aspect_ratio and aspect_ratio != "1:1":
                final_prompt = (
                    f"Generate image in {aspect_ratio} aspect ratio. {prompt}"
                )
                logger.info(f"Added aspect_ratio to prompt: {aspect_ratio}")

            # Обновляем payload с финальным промптом
            payload["messages"] = [{"role": "user", "content": contents}]
            # Обновляем текст в contents
            for item in contents:
                if item.get("type") == "text":
                    item["text"] = final_prompt
                    break

            logger.info(
                f"OpenRouter request: model={model}, aspect_ratio={aspect_ratio}"
            )

            async with session.post(
                f"{config.OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                response_text = await response.text()
                logger.info(
                    f"OpenRouter raw response ({response.status}): {response_text[:2000]}"
                )

                if response.status != 200:
                    logger.error(f"OpenRouter API error: {response.status}")
                    return None

                try:
                    data = json.loads(response_text)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON: {e}")
                    return None

                # Проверяем структуру ответа
                if "choices" not in data or not data["choices"]:
                    logger.error(f"No choices in response: {data.keys()}")
                    return None

                message = data["choices"][0].get("message", {})

                # === ОСНОВНОЙ ПУТЬ: поле images ===
                images = message.get("images", [])
                logger.info(f"Found {len(images)} images in message.images")

                if images and len(images) > 0:
                    img_data = images[0]
                    logger.info(
                        f"First image type: {type(img_data)}, value: {str(img_data)[:200]}"
                    )

                    # Вариант 1: строка base64 напрямую
                    if isinstance(img_data, str):
                        if img_data.startswith("data:image"):
                            b64_data = img_data.split(",", 1)[1]
                            return base64.b64decode(b64_data)
                        else:
                            # Чистый base64 без префикса
                            return base64.b64decode(img_data)

                    # Вариант 2: словарь с url
                    elif isinstance(img_data, dict):
                        img_url = img_data.get("url") or img_data.get(
                            "image_url", {}
                        ).get("url", "")
                        if img_url:
                            if img_url.startswith("data:image"):
                                b64_data = img_url.split(",", 1)[1]
                                return base64.b64decode(b64_data)
                            else:
                                # Скачиваем по URL
                                async with session.get(
                                    img_url, timeout=30
                                ) as img_response:
                                    if img_response.status == 200:
                                        return await img_response.read()
                                    else:
                                        logger.error(
                                            f"Failed to download: {img_response.status}"
                                        )

                    # Вариант 3: bytes напрямую (маловероятно, но проверим)
                    elif isinstance(img_data, bytes):
                        return img_data

                # === ЗАПАСНОЙ ПУТЬ: content с base64 ===
                content = message.get("content", "")
                if content:
                    logger.info(f"Checking content, length: {len(content)}")

                    # Ищем data URI
                    if "data:image" in content:
                        # Извлекаем все data URI
                        data_uris = re.findall(
                            r"data:image/[^;]+;base64,([A-Za-z0-9+/=]+)", content
                        )
                        if data_uris:
                            logger.info(
                                f"Found {len(data_uris)} base64 images in content"
                            )
                            return base64.b64decode(data_uris[0])

                    # Ищем URL изображения
                    url_match = re.search(
                        r"https?://\S+\.(?:png|jpg|jpeg|webp|gif)",
                        content,
                        re.IGNORECASE,
                    )
                    if url_match:
                        img_url = url_match.group(0)
                        logger.info(f"Found URL in content: {img_url[:50]}...")
                        async with session.get(img_url, timeout=30) as img_response:
                            if img_response.status == 200:
                                return await img_response.read()

                # === ПРОВЕРКА НА ВЛОЖЕННЫЕ ИЗОБРАЖЕНИЯ В ДРУГИХ ПОЛЯХ ===
                # Иногда OpenRouter кладёт в другое место
                for key in ["image", "attachments", "media", "files"]:
                    if key in message:
                        logger.info(
                            f"Found alternative field '{key}': {type(message[key])}"
                        )

                logger.error(
                    f"No image found in any expected field. Message keys: {message.keys()}"
                )
                return None

        except Exception as e:
            logger.exception(f"OpenRouter generation failed: {e}")
            return None

    async def _debug_openrouter_response(self, prompt: str = "A simple red circle"):
        """Метод для диагностики структуры ответа OpenRouter"""
        from bot.config import config

        session = await self._get_session()

        payload = {
            "model": "google/gemini-2.0-flash-exp:free",
            "messages": [{"role": "user", "content": prompt}],
            "modalities": ["image", "text"],
        }

        headers = {
            "Authorization": f"Bearer {self.openrouter_key}",
            "Content-Type": "application/json",
        }

        async with session.post(
            f"{config.OPENROUTER_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
        ) as response:
            data = await response.json()

            # Рекурсивно обходим структуру
            def explore(obj, path="", max_depth=5, current_depth=0):
                if current_depth > max_depth:
                    return

                if isinstance(obj, dict):
                    for k, v in obj.items():
                        new_path = f"{path}.{k}" if path else k
                        if isinstance(v, str) and len(v) > 100:
                            # Вероятно base64 или URL
                            preview = v[:100]
                            logger.info(
                                f"{new_path}: str(len={len(v)}, preview={preview}...)"
                            )
                        elif isinstance(v, (dict, list)):
                            explore(v, new_path, max_depth, current_depth + 1)
                        else:
                            logger.info(f"{new_path}: {type(v).__name__} = {v}")
                elif isinstance(obj, list) and len(obj) > 0:
                    logger.info(f"{path}: list[{len(obj)}]")
                    for i, item in enumerate(obj[:3]):  # Первые 3 элемента
                        explore(item, f"{path}[{i}]", max_depth, current_depth + 1)

            logger.info("=== OpenRouter Response Structure ===")
            explore(data)
            logger.info("======================================")

            return data

    async def _generate_via_native_gemini(
        self,
        prompt: str,
        model: str = "gemini-2.5-flash-image",
        image_input: Optional[bytes] = None,
        aspect_ratio: Optional[str] = None,
        resolution: str = "1K",
        enable_search: bool = False,
        reference_images: List[bytes] = None,
    ) -> Optional[bytes]:
        """Генерация через нативный Gemini API"""
        try:
            from google.genai import types

            contents = [prompt]

            # Добавляем референсные изображения
            if reference_images:
                for ref_img in reference_images[:14]:
                    img = Image.open(io.BytesIO(ref_img))
                    contents.append(img)

            if image_input:
                img = Image.open(io.BytesIO(image_input))
                contents.append(img)

            # Формируем конфиг согласно banana_api.md
            config_params = types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"]
            )

            # Добавляем image_config для Pro модели
            if aspect_ratio or resolution != "1K":
                config_params.image_config = types.ImageConfig(
                    aspect_ratio=aspect_ratio, image_size=resolution
                )

            # Добавляем tools для search grounding
            if enable_search:
                config_params.tools = [{"google_search": {}}]

            response = await self.client.models.generate_content_async(
                model=model, contents=contents, config=config_params
            )

            for part in response.parts:
                if part.inline_data:
                    logger.info(
                        f"Native Gemini image: {len(part.inline_data.data)} bytes"
                    )
                    return part.inline_data.data

            return None

        except ImportError as e:
            logger.error(f"Missing dependency: {e}")
        except Exception as e:
            logger.exception(f"Native Gemini generation failed: {e}")

        return None

    # =========================================================================
    # МНОГОХОДОВОЕ РЕДАКТИРОВАНИЕ (согласно banana_api.md)
    # =========================================================================

    async def create_chat(
        self,
        chat_id: str,
        model: str = "gemini-3-pro-image-preview",
        enable_search: bool = False,
    ) -> bool:
        """
        Создаёт чат для многоходового редактирования
        Согласно banana_api.md: используется для итеративной работы с изображением
        """
        if not self.client:
            logger.error("Chat requires native Gemini API")
            return False

        try:
            from google.genai import types

            config = types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"])

            if enable_search:
                config.tools = [{"google_search": {}}]

            chat = self.client.chats.create(model=model, config=config)
            self._chats[chat_id] = chat
            logger.info(f"Chat created: {chat_id}")
            return True

        except Exception as e:
            logger.exception(f"Failed to create chat: {e}")
            return False

    async def send_message_to_chat(
        self,
        chat_id: str,
        message: str,
        image_input: Optional[bytes] = None,
    ) -> Optional[bytes]:
        """
        Отправляет сообщение в чат для многоходового редактирования
        Согласно banana_api.md: позволяет итеративно улучшать изображение
        """
        if chat_id not in self._chats:
            logger.error(f"Chat {chat_id} not found")
            return None

        try:
            contents = [message]

            if image_input:
                img = Image.open(io.BytesIO(image_input))
                contents.append(img)

            response = await self._chats[chat_id].send_message_async(contents)

            for part in response.parts:
                if part.inline_data:
                    return part.inline_data.data

            return None

        except Exception as e:
            logger.exception(f"Chat message failed: {e}")
            return None

    async def close_chat(self, chat_id: str) -> bool:
        """Закрывает чат"""
        if chat_id in self._chats:
            del self._chats[chat_id]
            return True
        return False

    # =========================================================================
    # РЕДАКТИРОВАНИЕ ИЗОБРАЖЕНИЙ (согласно banana_api.md)
    # =========================================================================

    async def edit_image(
        self,
        image_bytes: bytes,
        instruction: str,
        model: str = "gemini-2.5-flash-image",
        enable_search: bool = False,
    ) -> Optional[bytes]:
        """
        Редактирование изображения (text-and-image-to-image)
        Согласно banana_api.md:
        - Добавление/удаление элементов
        - Смена стиля (style transfer)
        - Inpainting
        """
        return await self.generate_image(
            prompt=instruction,
            model=model,
            image_input=image_bytes,
            enable_search=enable_search,
        )

    async def add_element(
        self,
        image_bytes: bytes,
        element: str,
        model: str = "gemini-2.5-flash-image",
    ) -> Optional[bytes]:
        """Добавляет элемент к изображению согласно banana_api.md"""
        prompt = f"Using the provided image, add {element} to the scene. Ensure the addition matches the original lighting, perspective, and style. Seamless integration, photorealistic blend"
        return await self.edit_image(image_bytes, prompt, model)

    async def remove_element(
        self,
        image_bytes: bytes,
        element: str,
        model: str = "gemini-2.5-flash-image",
    ) -> Optional[bytes]:
        """Удаляет элемент с изображения согласно banana_api.md"""
        prompt = f"Remove the {element} from the provided image. Maintain the original style, lighting, and fill the space naturally"
        return await self.edit_image(image_bytes, prompt, model)

    async def style_transfer(
        self,
        image_bytes: bytes,
        style: str,
        model: str = "gemini-2.5-flash-image",
    ) -> Optional[bytes]:
        """Применяет стиль к изображению согласно banana_api.md"""
        prompt = f"Transform the provided image into {style} artistic style. Preserve the original composition and subject matter, but render with {style} characteristic techniques, colors, and brushwork"
        return await self.edit_image(image_bytes, prompt, model)

    async def replace_element(
        self,
        image_bytes: bytes,
        old_element: str,
        new_element: str,
        model: str = "gemini-2.5-flash-image",
    ) -> Optional[bytes]:
        """Заменяет элемент на изображении согласно banana_api.md"""
        prompt = f"In the provided image, change only the {old_element} to {new_element}. Keep everything else in the image exactly the same, preserving the original style, lighting, and composition"
        return await self.edit_image(image_bytes, prompt, model)

    async def composite_images(
        self,
        base_image: bytes,
        overlay_image: bytes,
        instruction: str,
        model: str = "gemini-2.5-flash-image",
    ) -> Optional[bytes]:
        """Объединяет несколько изображений согласно banana_api.md"""
        # Формируем промпт для объединения
        prompt = f"Create a new image by combining the provided images. {instruction}"
        return await self.generate_image(
            prompt=prompt,
            model=model,
            image_input=base_image,
            reference_images=[overlay_image] if overlay_image else None,
        )

    # =========================================================================
    # РАБОТА С РЕФЕРЕНСНЫМИ ИЗОБРАЖЕНИЯМИ (согласно banana_api.md)
    # =========================================================================

    async def generate_with_references(
        self,
        prompt: str,
        reference_images: List[bytes],
        person_references: List[bytes] = None,
        model: str = "gemini-3-pro-image-preview",
        aspect_ratio: str = "1:1",
        resolution: str = "2K",
    ) -> Optional[bytes]:
        """
        Генерация с референсными изображениями
        Согласно banana_api.md:
        - До 14 референсов всего
        - До 6 объектов с высокой детализацией
        - До 5 людей для согласованности персонажей
        """
        all_references = []

        if reference_images:
            # Ограничение до 6 объектов
            all_references.extend(reference_images[:6])

        if person_references:
            # Ограничение до 5 людей
            all_references.extend(person_references[:5])

        # Всего не более 14
        all_references = all_references[:14]

        return await self.generate_image(
            prompt=prompt,
            model=model,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            reference_images=all_references,
        )

    # =========================================================================
    # SEARCH GROUNDING (согласно banana_api.md)
    # =========================================================================

    async def generate_with_search(
        self,
        prompt: str,
        model: str = "gemini-3-pro-image-preview",
        aspect_ratio: str = "16:9",
    ) -> Optional[bytes]:
        """
        Генерация с поисковым заземлением (Grounding)
        Согласно banana_api.md: использует Google Search для актуальной информации
        """
        return await self.generate_image(
            prompt=prompt,
            model=model,
            aspect_ratio=aspect_ratio,
            enable_search=True,
        )

    # =========================================================================
    # HIGH RESOLUTION (согласно banana_api.md)
    # =========================================================================

    async def generate_high_res(
        self,
        prompt: str,
        resolution: str = "4K",
        model: str = "gemini-3-pro-image-preview",
        aspect_ratio: str = "1:1",
    ) -> Optional[bytes]:
        """
        Генерация высокого разрешения
        Согласно banana_api.md: 1K, 2K, 4K
        """
        return await self.generate_image(
            prompt=prompt,
            model=model,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
        )

    # =========================================================================
    # THINKING PROCESS (согласно banana_api.md)
    # =========================================================================

    async def generate_with_thinking(
        self,
        prompt: str,
        model: str = "gemini-3-pro-image-preview",
    ) -> Optional[Dict[str, Any]]:
        """
        Генерация с thinking процессом
        Согласно banana_api.md: Gemini 3 Pro использует reasoning для сложных промптов
        Возвращает словарь с изображением и мыслями
        """
        if not self.client:
            logger.error("Thinking requires native Gemini API")
            return None

        try:
            from google.genai import types

            config = types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"])

            response = await self.client.models.generate_content_async(
                model=model, contents=[prompt], config=config
            )

            result = {
                "image": None,
                "thoughts": [],
                "text": None,
            }

            for part in response.parts:
                if hasattr(part, "thought") and part.thought:
                    # Это мыслительный процесс
                    if part.text:
                        result["thoughts"].append(part.text)
                    if part.inline_data:
                        result["thoughts"].append("[thought_image]")
                else:
                    # Финальный результат
                    if part.text:
                        result["text"] = part.text
                    if part.inline_data:
                        result["image"] = part.inline_data.data

            return result

        except Exception as e:
            logger.exception(f"Thinking generation failed: {e}")
            return None

    # =========================================================================
    # РАЗЛИЧНЫЕ СТИЛИ ГЕНЕРАЦИИ (согласно banana_api.md)
    # =========================================================================

    async def generate_photorealistic(
        self,
        prompt: str,
        model: str = "gemini-2.5-flash-image",
    ) -> Optional[bytes]:
        """
        Генерация фотореалистичного изображения
        Согласно banana_api.md: используем фотографические термины
        """
        # Добавляем фотографические термины для реализма
        enhanced_prompt = (
            f"A photorealistic {prompt}. "
            "Shot with professional camera, natural lighting, "
            "high detail, realistic textures, shallow depth of field"
        )
        return await self.generate_image(prompt=enhanced_prompt, model=model)

    async def generate_sticker(
        self,
        prompt: str,
        model: str = "gemini-2.5-flash-image",
    ) -> Optional[bytes]:
        """
        Генерация стикера/иконки
        Согласно banana_api.md: прозрачный фон, чистые линии
        """
        enhanced_prompt = (
            f"A sticker of {prompt}. Bold clean outlines, "
            "simple cel-shading, vibrant colors, transparent background"
        )
        return await self.generate_image(prompt=enhanced_prompt, model=model)

    async def generate_product_photo(
        self,
        product_description: str,
        model: str = "gemini-2.5-flash-image",
    ) -> Optional[bytes]:
        """
        Генерация коммерческой фотографии продукта
        Согласно banana_api.md: студийное освещение, чистый фон
        """
        enhanced_prompt = (
            f"A high-resolution, studio-lit product photograph of {product_description}. "
            "Three-point softbox lighting, clean background, "
            "professional commercial photography, ultra-realistic"
        )
        return await self.generate_image(prompt=enhanced_prompt, model=model)

    async def generate_with_text(
        self,
        text: str,
        style: str = "modern",
        model: str = "gemini-3-pro-image-preview",
    ) -> Optional[bytes]:
        """
        Генерация изображения с текстом
        Согласно banana_api.md: Gemini 3 Pro лучше всего справляется с рендерингом текста
        """
        enhanced_prompt = (
            f"Create a design with the text '{text}' in a {style} style. "
            "Clear, legible typography, professional design, "
            "clean composition"
        )
        return await self.generate_image(prompt=enhanced_prompt, model=model)

    async def generate_comic(
        self,
        prompt: str,
        model: str = "gemini-3-pro-image-preview",
    ) -> Optional[bytes]:
        """
        Генерация комикса/иллюстрации
        Согласно banana_api.md: последовательные панели
        """
        enhanced_prompt = (
            f"Make a comic panel: {prompt}. "
            "Comic book art style, dynamic composition, "
            "clear storytelling, vibrant colors"
        )
        return await self.generate_image(prompt=enhanced_prompt, model=model)

    async def generate_minimalist(
        self,
        subject: str,
        position: str = "center",
        model: str = "gemini-2.5-flash-image",
    ) -> Optional[bytes]:
        """
        Генерация минималистичного дизайна
        Согласно banana_api.md: много негативного пространства
        """
        enhanced_prompt = (
            f"A minimalist composition featuring a {subject} "
            f"positioned in the {position} of the frame. "
            "Vast empty background, significant negative space, "
            "soft subtle lighting, clean design"
        )
        return await self.generate_image(prompt=enhanced_prompt, model=model)

    # =========================================================================
    # СЛУЖЕБНЫЕ МЕТОДЫ
    # =========================================================================

    async def close(self):
        """Закрытие HTTP сессии"""
        if self._session and not self._session.closed:
            await self._session.close()


# Инициализация сервиса
from bot.config import config

gemini_service = GeminiService(
    api_key=config.GEMINI_API_KEY,
    nanobanana_key=config.NANOBANANA_API_KEY,
    openrouter_key=config.OPENROUTER_API_KEY,
)
