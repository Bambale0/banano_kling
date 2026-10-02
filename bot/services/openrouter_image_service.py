"""Gemini image generation using OpenRouter's dedicated, synchronous Image API."""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import aiohttp
from PIL import Image

from bot.config import config

MODEL = "google/gemini-3-pro-image"
MAX_RESPONSE_BYTES = 64 * 1024 * 1024


class ImageProviderError(RuntimeError):
    """Safe for displaying: never includes raw provider payloads or credentials."""

    def __init__(self, message: str, *, code: str = "provider_error"):
        super().__init__(message)
        self.code = code


@dataclass
class GeneratedImage:
    data: bytes
    extension: str


@dataclass
class ImageResult:
    images: list[GeneratedImage]
    request_id: str
    usage: dict[str, Any]


class OpenRouterImageService:
    def __init__(self, *, api_key: str | None = None, base_url: str | None = None):
        self.api_key = config.OPENROUTER_API_KEY if api_key is None else api_key
        self.base_url = (
            config.OPENROUTER_BASE_URL if base_url is None else base_url
        ).rstrip("/")
        self._capabilities: list[dict[str, Any]] = []
        self._cached_at = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def capabilities(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        if (
            not refresh
            and self._capabilities
            and time.monotonic() - self._cached_at < 300
        ):
            return self._capabilities
        try:
            async with (
                aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as session,
                session.get(
                    f"{self.base_url}/images/models/{MODEL}/endpoints"
                ) as response,
            ):
                if response.status != 200:
                    raise ImageProviderError(
                        "Не удалось получить возможности OpenRouter. Обновите экран позже."
                    )
                data = await response.json()
            endpoints = data.get("endpoints") if isinstance(data, dict) else None
            if not isinstance(endpoints, list) or not endpoints:
                raise ImageProviderError("Модель временно недоступна в OpenRouter.")
            valid = [e for e in endpoints if self._valid_endpoint(e)]
            if not valid:
                raise ImageProviderError(
                    "OpenRouter не вернул доступных провайдеров модели.",
                    code="capabilities_invalid",
                )
            self._capabilities = valid
            self._cached_at = time.monotonic()
            return valid
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise ImageProviderError(
                "Не удалось загрузить параметры OpenRouter. Повторите позже."
            ) from exc

    @staticmethod
    def _valid_endpoint(endpoint: Any) -> bool:
        if not isinstance(endpoint, dict):
            return False
        if (
            not isinstance(endpoint.get("provider_name"), str)
            or not endpoint["provider_name"]
        ):
            return False
        tag = endpoint.get("provider_tag")
        if not isinstance(tag, str) or not tag or len(tag.encode()) > 40:
            return False  # Telegram callback_data is bounded to 64 bytes.
        params = endpoint.get("supported_parameters")
        if not isinstance(params, dict):
            return False
        for field in ("resolution", "aspect_ratio"):
            parameter = params.get(field)
            if not isinstance(parameter, dict):
                return False
            values = parameter.get("values")
            if (
                not isinstance(values, list)
                or not values
                or not all(
                    isinstance(v, str) and 0 < len(v.encode()) <= 12 for v in values
                )
            ):
                return False
        references = params.get("input_references")
        return (
            isinstance(references, dict)
            and type(references.get("max")) is int
            and references["max"] >= 0
        )

    @staticmethod
    def options(
        capabilities: list[dict[str, Any]], provider: str = "auto"
    ) -> dict[str, Any]:
        endpoints = [
            e
            for e in capabilities
            if provider == "auto" or e["provider_tag"] == provider
        ]
        if not endpoints:
            raise ValueError("Провайдер недоступен. Выберите другого.")
        result: dict[str, Any] = {
            "resolution": [],
            "aspect_ratio": [],
            "max_references": 0,
        }
        for endpoint in endpoints:
            params = endpoint["supported_parameters"]
            for field in ("resolution", "aspect_ratio"):
                for value in params.get(field, {}).get("values", []):
                    if isinstance(value, str) and value not in result[field]:
                        result[field].append(value)
            result["max_references"] = max(
                result["max_references"],
                int(params.get("input_references", {}).get("max", 0)),
            )
        return result

    @staticmethod
    def build_payload(
        *,
        prompt: str,
        references: list[str],
        ratio: str,
        resolution: str,
        provider: str,
        capabilities: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not prompt.strip():
            raise ValueError("Сначала введите промпт.")
        eligible = []
        for endpoint in capabilities:
            if provider != "auto" and endpoint["provider_tag"] != provider:
                continue
            params = endpoint["supported_parameters"]
            if resolution not in params.get("resolution", {}).get("values", []):
                continue
            if ratio != "auto" and ratio not in params.get("aspect_ratio", {}).get(
                "values", []
            ):
                continue
            if len(references) > int(params.get("input_references", {}).get("max", 0)):
                continue
            eligible.append(endpoint["provider_tag"])
        if not eligible:
            raise ValueError(
                "Эта комбинация провайдера, разрешения, формата и референсов недоступна. Измените настройки."
            )
        for reference in references:
            url = urlparse(reference)
            if (
                url.scheme not in ("https", "http")
                or not url.hostname
                or url.username
                or url.password
            ):
                raise ValueError("Некорректный референс. Загрузите изображение заново.")
        payload: dict[str, Any] = {
            "model": MODEL,
            "prompt": prompt.strip(),
            "n": 1,
            "resolution": resolution,
            "provider": {"only": eligible},
        }
        if ratio != "auto":
            payload["aspect_ratio"] = ratio
        if references:
            payload["input_references"] = [
                {"type": "image_url", "image_url": {"url": url}} for url in references
            ]
        return payload

    async def generate(self, *, timeout: int = 240, **kwargs: Any) -> ImageResult:
        if not self.enabled:
            raise ImageProviderError(
                "Ключ OpenRouter не настроен на сервере.", code="not_configured"
            )
        payload = self.build_payload(**kwargs)
        try:
            # No automatic POST retry: an interrupted request may already be billed.
            async with (
                aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as session,
                session.post(
                    f"{self.base_url}/images",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                ) as response,
            ):
                if response.status != 200:
                    messages = {
                        401: "OpenRouter отклонил ключ API.",
                        403: "Модель запрещена для этого ключа OpenRouter.",
                        402: "Недостаточно средств на аккаунте OpenRouter.",
                        429: "Лимит OpenRouter. Попробуйте позже.",
                    }
                    raise ImageProviderError(
                        messages.get(
                            response.status,
                            f"OpenRouter не выполнил запрос (HTTP {response.status}). Автоповтор отключён.",
                        ),
                        code=f"http_{response.status}",
                    )
                raw = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise ImageProviderError(
                            "Ответ OpenRouter слишком большой. Попробуйте меньшее разрешение.",
                            code="response_too_large",
                        )
                data = json.loads(raw)
            if not isinstance(data, dict) or data.get("error"):
                raise ImageProviderError(
                    "OpenRouter вернул ошибку. Измените запрос или попробуйте позже.",
                    code="provider_rejection",
                )
            images = []
            for item in data.get("data") or []:
                image_data = base64.b64decode(item["b64_json"], validate=True)
                with Image.open(io.BytesIO(image_data)) as img:
                    extension = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}.get(
                        img.format
                    )
                    img.verify()
                if not extension:
                    raise ImageProviderError(
                        "OpenRouter вернул неподдерживаемый формат изображения."
                    )
                images.append(GeneratedImage(image_data, extension))
            if not images:
                raise ImageProviderError(
                    "Изображение не получено: возможен отказ модели. Попробуйте изменить промпт.",
                    code="empty_result",
                )
            return ImageResult(
                images,
                str(data.get("id") or ""),
                data["usage"] if isinstance(data.get("usage"), dict) else {},
            )
        except asyncio.TimeoutError as exc:
            raise ImageProviderError(
                "Время ожидания истекло. Запрос мог выполниться у провайдера. Автоповтора нет; проверьте OpenRouter Activity перед новым запуском.",
                code="timeout",
            ) from exc
        except aiohttp.ClientError as exc:
            raise ImageProviderError(
                "Соединение с OpenRouter прервано. Запрос мог выполниться; автоповтора нет.",
                code="network_interrupted",
            ) from exc
        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            OSError,
            binascii.Error,
            Image.DecompressionBombError,
        ) as exc:
            raise ImageProviderError(
                "OpenRouter вернул некорректный ответ. Автоповтор отключён.",
                code="response_invalid",
            ) from exc


openrouter_image_service = OpenRouterImageService()
