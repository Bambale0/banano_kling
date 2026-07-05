"""Helpers for turning backend/provider failures into friendly user text."""

from __future__ import annotations

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

    text = _PROVIDER_RE.sub("сервис генерации", text)
    text = re.sub(r"\bAPI error\b", "ошибка сервиса", text, flags=re.IGNORECASE)
    text = text.replace("API", "сервис")
    return text
