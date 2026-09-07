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
_DATE_FIELD_HINTS = (
    "дата",
    "date",
    "день рождения",
    "birthday",
)


class TrendUserFieldsError(ValueError):
    """User-safe validation error for configurable trend fields."""


@dataclass(frozen=True)
class TrendUserFieldSpec:
    key: str
    label: str
    field_type: str
    required: bool = True
    max_length: int = MAX_FIELD_VALUE_LENGTH


def infer_field_type(label: str) -> str:
    normalized = str(label or "").strip().lower()
    if any(hint in normalized for hint in _DATE_FIELD_HINTS):
        return "date"
    if any(hint in normalized for hint in _NUMBER_FIELD_HINTS):
        return "number"
    return "text"


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
            continue
        if key not in keys:
            keys.append(key)
        if len(keys) >= MAX_USER_FIELDS:
            break
    return tuple(keys)


def _normalize_configured_fields(raw_fields: Any) -> list[dict[str, Any]]:
    if raw_fields in (None, ""):
        return []
    if not isinstance(raw_fields, list):
        raise TrendUserFieldsError("Поля шаблона настроены неверно")
    if len(raw_fields) > MAX_USER_FIELDS:
        raise TrendUserFieldsError(
            f"В одном тренде можно использовать не больше {MAX_USER_FIELDS} полей"
        )

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_field in raw_fields:
        if not isinstance(raw_field, Mapping):
            raise TrendUserFieldsError("Поля шаблона настроены неверно")
        label = str(raw_field.get("label") or raw_field.get("key") or "").strip()
        key = str(raw_field.get("key") or label).strip()
        if (
            not key
            or not label
            or len(key) > MAX_FIELD_KEY_LENGTH
            or len(label) > MAX_FIELD_LABEL_LENGTH
            or "{{" in key
            or "}}" in key
        ):
            raise TrendUserFieldsError("Поля шаблона настроены неверно")
        dedupe_key = key.casefold()
        if dedupe_key in seen:
            raise TrendUserFieldsError("Поля шаблона не должны повторяться")
        seen.add(dedupe_key)

        normalized.append(
            {
                "key": key,
                "label": label,
                "type": infer_field_type(label),
                "required": True,
                "max_length": MAX_FIELD_VALUE_LENGTH,
            }
        )
    return normalized


def configured_user_fields(
    settings: Mapping[str, Any] | None,
    *,
    prompt: str = "",
) -> list[dict[str, Any]]:
    """Return safe fields selected by the admin.

    New trends store explicit admin-selected fields in generation_settings.
    Legacy {{...}} prompts are still supported as a fallback so old trends do
    not break, but new admins never need to write template tokens manually.
    """

    raw_settings = settings if isinstance(settings, Mapping) else {}
    fields = _normalize_configured_fields(raw_settings.get("user_fields"))
    if fields:
        return fields

    # Compatibility for trends created by the previous token-based flow.
    return [
        {
            "key": key,
            "label": key,
            "type": infer_field_type(key),
            "required": True,
            "max_length": MAX_FIELD_VALUE_LENGTH,
        }
        for key in _template_keys(prompt)
    ]


def normalize_user_fields_settings(
    settings: Mapping[str, Any] | None,
    *,
    prompt: str = "",
) -> dict[str, Any]:
    """Normalize admin-selected fields while leaving provider settings intact."""

    normalized = dict(settings or {})
    fields = configured_user_fields(normalized, prompt=prompt)
    if fields:
        normalized["user_fields"] = fields
    else:
        normalized.pop("user_fields", None)
    return normalized


def _field_specs(
    settings: Mapping[str, Any],
    *,
    prompt: str,
) -> tuple[TrendUserFieldSpec, ...]:
    return tuple(
        TrendUserFieldSpec(
            key=str(field["key"]),
            label=str(field["label"]),
            field_type=str(field["type"]),
            required=bool(field.get("required", True)),
            max_length=MAX_FIELD_VALUE_LENGTH,
        )
        for field in configured_user_fields(settings, prompt=prompt)
    )


def _validated_field_value(spec: TrendUserFieldSpec, raw_value: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        if spec.required:
            raise TrendUserFieldsError(f"Заполните поле «{spec.label}»")
        return ""
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
    """Apply user-editable admin fields to a hidden trend prompt server-side.

    New flow: the admin selects fields in UX and never edits {{tokens}}.
    User values are appended as authoritative overrides. Legacy matching tokens
    are substituted too, so older trends continue to work.
    """

    base_prompt = str(prompt or "").strip()
    values = dict(user_values or {})
    specs = _field_specs(settings, prompt=base_prompt)
    if not specs:
        if values:
            raise TrendUserFieldsError("Этот тренд не принимает дополнительные поля")
        return base_prompt

    allowed = {spec.key for spec in specs}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise TrendUserFieldsError("Переданы лишние поля тренда")

    validated = {
        spec.key: _validated_field_value(spec, values.get(spec.key, ""))
        for spec in specs
    }

    rendered = base_prompt
    for spec in specs:
        token_pattern = re.compile(r"\{\{\s*" + re.escape(spec.key) + r"\s*\}\}")
        rendered = token_pattern.sub(validated[spec.key], rendered)

    # Values selected by the user must win over any conflicting wording in the
    # base prompt. Keeping this server-side also preserves prompt privacy.
    overrides = "\n".join(
        f"- {spec.label}: {validated[spec.key]}"
        for spec in specs
        if validated[spec.key]
    )
    if overrides:
        rendered = (
            f"{rendered}\n\n"
            "ВАЖНО: примените следующие параметры пользователя как приоритетные "
            "изменения. Если они противоречат исходному prompt, значения ниже имеют "
            f"приоритет. Остальные детали сохраните без изменений:\n{overrides}"
        )
    return rendered.strip()
