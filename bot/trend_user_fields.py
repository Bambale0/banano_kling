from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

MAX_USER_FIELDS = 6
MAX_FIELD_KEY_LENGTH = 48
MAX_FIELD_LABEL_LENGTH = 64
MAX_FIELD_VALUE_LENGTH = 160

_TEMPLATE_RE = re.compile(r"\{\{([^{}]+)\}\}")
_NUMBER_RE = re.compile(r"^-?\d+(?:[\.,]\d+)?$")

_NUMBER_FIELD_HINTS = (
    "возраст",
    "число",
    "цифр",
    "количество",
    "номер",
    "рост",
    "вес",
    "лет",
    "год",
    "свеч",
)

_TEXT_FIELD_HINTS = (
    "имя",
    "текст",
    "надпись",
    "слово",
    "цвет",
    "стиль",
    "город",
    "страна",
    "професс",
    "одеж",
    "причес",
    "волос",
    "фон",
)


def _infer_field_type(key: str, prompt: str) -> str:
    normalized_key = str(key or "").strip().lower()
    if any(hint in normalized_key for hint in _TEXT_FIELD_HINTS):
        return "text"
    if any(hint in normalized_key for hint in _NUMBER_FIELD_HINTS):
        return "number"

    token = "{{" + str(key or "").strip() + "}}"
    prompt_text = str(prompt or "")
    position = prompt_text.find(token)
    if position >= 0:
        context = prompt_text[max(0, position - 32) : position + len(token) + 32].lower()
        context = _TEMPLATE_RE.sub(" ", context)
    else:
        context = ""
    return "number" if any(hint in context for hint in _NUMBER_FIELD_HINTS) else "text"


class TrendUserFieldsError(ValueError):
    """User-safe validation error for configurable trend fields."""


@dataclass(frozen=True)
class TrendUserFieldSpec:
    key: str
    label: str
    field_type: str
    required: bool = True
    max_length: int = MAX_FIELD_VALUE_LENGTH


def clean_submitted_user_values(raw_values: Any) -> dict[str, str]:
    if raw_values in (None, ""):
        return {}
    if not isinstance(raw_values, Mapping):
        raise TrendUserFieldsError("Некорректные дополнительные поля тренда")
    if len(raw_values) > MAX_USER_FIELDS:
        raise TrendUserFieldsError("Слишком много дополнительных полей")

    cleaned: dict[str, str] = {}
    for raw_key, raw_value in raw_values.items():
        key = str(raw_key or "").strip()
        if not key or len(key) > MAX_FIELD_KEY_LENGTH or "{{" in key or "}}" in key:
            raise TrendUserFieldsError("Некорректное дополнительное поле")
        if isinstance(raw_value, (Mapping, list, tuple, set)):
            raise TrendUserFieldsError(f"Некорректное значение поля «{key}»")
        value = str(raw_value if raw_value is not None else "").strip()
        if len(value) > MAX_FIELD_VALUE_LENGTH:
            raise TrendUserFieldsError(f"Слишком длинное значение поля «{key}»")
        cleaned[key] = value
    return cleaned


def _template_keys(prompt: str) -> tuple[str, ...]:
    keys: list[str] = []
    for match in _TEMPLATE_RE.finditer(str(prompt or "")):
        key = match.group(1).strip()
        if not key or len(key) > MAX_FIELD_KEY_LENGTH:
            raise TrendUserFieldsError(
                "Название параметра в {{...}} должно быть от 1 до 48 символов"
            )
        if key not in keys:
            keys.append(key)
        if len(keys) > MAX_USER_FIELDS:
            raise TrendUserFieldsError(
                f"В одном тренде можно использовать не больше {MAX_USER_FIELDS} параметров"
            )
    return tuple(keys)


def infer_user_fields_from_prompt(prompt: str) -> list[dict[str, Any]]:
    """Build safe runner fields directly from hidden-prompt ``{{...}}`` tokens.

    The hidden prompt is the single source of truth: admins do not configure
    field types, ranges or placeholders separately. Every unique token becomes
    one required free-form value that is substituted server-side.
    """

    return [
        {
            "key": key,
            "label": key,
            "type": _infer_field_type(key, prompt),
            "required": True,
            "max_length": MAX_FIELD_VALUE_LENGTH,
        }
        for key in _template_keys(prompt)
    ]


def apply_inferred_user_fields(
    prompt: str,
    settings: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return generation settings with user fields derived from the prompt."""

    normalized = dict(settings or {})
    fields = infer_user_fields_from_prompt(prompt)
    if fields:
        normalized["user_fields"] = fields
    else:
        normalized.pop("user_fields", None)
    return normalized


def _field_specs_from_prompt(prompt: str) -> tuple[TrendUserFieldSpec, ...]:
    return tuple(
        TrendUserFieldSpec(
            key=field["key"],
            label=field["label"],
            field_type=field["type"],
        )
        for field in infer_user_fields_from_prompt(prompt)
    )


def _validated_field_value(spec: TrendUserFieldSpec, raw_value: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        raise TrendUserFieldsError(f"Заполните поле «{spec.label}»")
    if spec.field_type == "number" and not _NUMBER_RE.fullmatch(value):
        raise TrendUserFieldsError(f"Поле «{spec.label}» должно быть числом")
    if len(value) > spec.max_length:
        raise TrendUserFieldsError(
            f"Поле «{spec.label}» должно быть короче {spec.max_length + 1} символов"
        )
    return value


def render_trend_prompt(
    prompt: str,
    settings: Mapping[str, Any],
    user_values: Mapping[str, str] | None = None,
) -> str:
    # ``settings`` stays in the signature for API compatibility. Template
    # parameters are intentionally inferred from the hidden prompt itself.
    _ = settings
    values = dict(user_values or {})
    specs = _field_specs_from_prompt(prompt)
    if not specs:
        if values:
            raise TrendUserFieldsError("Этот тренд не принимает дополнительные поля")
        return str(prompt or "").strip()

    allowed = {spec.key for spec in specs}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise TrendUserFieldsError("Переданы лишние поля тренда")

    validated = {
        spec.key: _validated_field_value(spec, values.get(spec.key, ""))
        for spec in specs
    }

    def replace_token(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        try:
            return validated[key]
        except KeyError as exc:
            raise TrendUserFieldsError(
                f"Шаблон содержит незаполненное поле «{key}»"
            ) from exc

    rendered = _TEMPLATE_RE.sub(replace_token, str(prompt or ""))
    unresolved = _TEMPLATE_RE.search(rendered)
    if unresolved:
        raise TrendUserFieldsError(
            f"Шаблон содержит незаполненное поле «{unresolved.group(1).strip()}»"
        )
    return rendered.strip()
