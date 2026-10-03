"""Helpers for turning backend/provider failures into friendly user text."""

from __future__ import annotations

import json
import re

_PROVIDER_RE = re.compile(r"\b(?:kie\.ai|kie)\b", re.IGNORECASE)
_API_KEY_RE = re.compile(r"\b(api\s*key|KIE_AI_API_KEY|authorization)\b", re.IGNORECASE)
_OVERLOAD_RE = re.compile(
    r"(system load|too high|try again later|server exception|temporar|overload|busy)",
    re.IGNORECASE,
)
_MISSING_RESULT_RE = re.compile(
    r"(response did not include|task id missing|no taskId|missing task|unexpected result type)",
    re.IGNORECASE,
)
_REAL_PERSON_IMAGE_RE = re.compile(
    r"input image.*(?:may contain|contains?).*real person|real person.*input image",
    re.IGNORECASE,
)
_CONTENT_INDEX_RE = re.compile(r"content\[(\d+)]", re.IGNORECASE)


def sanitize_provider_log_payload(value):
    """Keep diagnostic IDs/status while removing private media and recipe data."""
    private_fields = {
        "prompt", "negative_prompt", "system_prompt", "effective_prompt",
        "param", "params", "image_input", "image_urls", "input_urls",
        "reference_images", "source_reference_images", "private_repeat_reference_images",
        "reference_image_urls", "first_frame_url", "last_frame_url",
        "image_url", "file_url", "downloadurl", "base64data", "base64_data",
        "authorization", "api_key", "token", "secret",
    }
    if isinstance(value, dict):
        return {
            str(key): (
                f"[redacted:{len(item)} items]" if isinstance(item, list) else "[redacted]"
            ) if str(key).lower() in private_fields else sanitize_provider_log_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_provider_log_payload(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    if text.lstrip().startswith(("{", "[")):
        try:
            decoded = json.loads(text)
        except (TypeError, ValueError):
            pass
        else:
            return json.dumps(sanitize_provider_log_payload(decoded), ensure_ascii=False)
    text = re.sub(r"(?:https?://|https?%3a%2f%2f|data:|file://)[^\s<>\"']+", "[redacted:media]", text, flags=re.IGNORECASE)
    return re.sub(r"(?<!\w)/(?:[^\s/]+/)+(?:[^\s<>\"']+)", "[redacted:media]", text)


def make_user_friendly_generation_error(message: object | None) -> str | None:
    """Hide backend brand/details in errors shown to users."""
    if message is None:
        return None

    text = " ".join(str(message).split())
    if not text:
        return None

    if _API_KEY_RE.search(text):
        return "Сервис генерации временно недоступен. Мы уже видим проблему на нашей стороне."

    if _OVERLOAD_RE.search(text):
        return "Сервис генерации сейчас перегружен. Попробуйте ещё раз через минуту."

    if _MISSING_RESULT_RE.search(text):
        return "Сервис генерации не вернул готовый результат. Попробуйте ещё раз."

    if _REAL_PERSON_IMAGE_RE.search(text):
        match = _CONTENT_INDEX_RE.search(text)
        position = int(match.group(1)) + 1 if match else 1
        return (
            f"Seedance отклонил фото-референс №{position}: фильтр модели распознал "
            "на изображении возможного реального человека. Уточнение в промпте "
            "не меняет проверку самого изображения. Замените этот референс на "
            "явно вымышленного персонажа — например, иллюстрацию или 3D-рендер."
        )

    # Provider failures can echo private reference inputs, signed URLs or local
    # file paths. They must never turn error notifications into a disclosure.
    text = re.sub(r"(?:https?://|https?%3a%2f%2f|data:|file://)[^\s<>\"']+", "[скрытый ресурс]", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<!\w)/(?:[^\s/]+/)+(?:[^\s<>\"']+)", "[скрытый ресурс]", text)
    text = _PROVIDER_RE.sub("сервис генерации", text)
    text = re.sub(r"\bAPI error\b", "ошибка сервиса", text, flags=re.IGNORECASE)
    text = text.replace("API", "сервис")
    return text
