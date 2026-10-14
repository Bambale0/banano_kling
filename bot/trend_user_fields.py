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
    original_value: str = ""


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

        original_value_raw = raw_field.get("original_value")
        if original_value_raw is not None and not isinstance(original_value_raw, str):
            raise TrendUserFieldsError("Исходное значение поля настроено неверно")
        original_value = str(original_value_raw or "").strip()
        if len(original_value) > MAX_FIELD_VALUE_LENGTH:
            raise TrendUserFieldsError("Исходное значение поля слишком длинное")
        normalized.append(
            {
                "key": key,
                "label": label,
                "type": infer_field_type(label),
                "required": True,
                "max_length": MAX_FIELD_VALUE_LENGTH,
                **({"original_value": original_value} if original_value else {}),
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
    for field in fields:
        original = str(field.get("original_value") or "")
        if original and not _replace_literal(str(prompt or ""), original, "{{" + field["key"] + "}}")[1]:
            raise TrendUserFieldsError(
                f"Исходное значение поля «{field['label']}» не найдено в скрытом промпте"
            )
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
            original_value=str(field.get("original_value") or ""),
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


# Only a server-private recipe may carry the author's original text. The Mini App
# receives labels and types, never these bindings or the assembled prompt.
_DISPLAY_CUE_RE = re.compile(
    r"(?:цифр\w*|свечи[-\s]*цифр\w*|возраст\w*|числ\w*|"
    r"надпис\w*|написан\w*|видно|candle\w*|digit\w*|"
    r"number\w*|birthday)", re.IGNORECASE,
)
_DISPLAY_NUMBER_RE = re.compile(r"(?<![\w:])([1-9]\d{0,3})(?![\w:]|\.\d)")


def _replace_literal(prompt: str, source: str, value: str) -> tuple[str, int]:
    if not source:
        return prompt, 0
    # Numeric editing must not corrupt @Image1, timecodes, fps, dimensions or
    # other numbers merely containing the original digits.
    if source.isdigit():
        pattern = re.compile(
            r"(?<![\w:.])" + re.escape(source) + r"(?![\w:]|\.\d)"
        )
    else:
        pattern = re.compile(
            r"(?<!\w)" + re.escape(source) + r"(?!\w)"
        )
    return pattern.subn(lambda _: value, prompt)


def _infer_display_number(prompt: str) -> str | None:
    """Safely recognize one explicit number next to displayed-number language.

    Do not guess from timestamps, durations, reference indices or ambiguous
    multiple ages. Ambiguous templates retain the source and rely on a clear
    priority instruction until the admin supplies an explicit original_value.
    """
    candidates: set[str] = set()
    for cue in _DISPLAY_CUE_RE.finditer(prompt):
        # A forbidden/mirrored *example* number is not the desired value.
        # E.g. «ЗАПРЕЩЕНО писать число 73» after a positive 37.
        forbidden_prefix = prompt[max(0, cue.start() - 85):cue.start()]
        if re.search(
            r"(?i)(?:запрещено|не\s+писать|не\s+рисовать|избегать|never|avoid).{0,65}$",
            forbidden_prefix,
        ):
            continue
        region = prompt[cue.end():cue.end() + 56]
        # A timecode / new scene after a cue is not a displayed age.
        first_boundary = re.search(r"[\n\[\]•]", region)
        if first_boundary:
            region = region[:first_boundary.start()]
        match = _DISPLAY_NUMBER_RE.search(region)
        if not match:
            continue
        source = match.group(1)
        # A compact comma/dot-separated shot duration is not an age.
        if match.start() and region[match.start() - 1] in ".:":
            continue
        candidates.add(source)
        if len(candidates) > 1:
            return None
    return next(iter(candidates), None)


def _is_display_number_field(spec: TrendUserFieldSpec, value: str) -> bool:
    name = spec.label.lower()
    return bool(
        value.isdecimal()
        and (
            any(hint in name for hint in ("цифр", "возраст", "свеч", "число", "номер", "лет"))
            or name in {"надпись", "number", "age", "digits"}
        )
    )


def render_trend_prompt(
    prompt: str,
    settings: Mapping[str, Any],
    user_values: Mapping[str, str] | None = None,
) -> str:
    """Apply user-editable admin fields to a hidden trend prompt server-side.

    Assemble the complete private base on the server. Admin-provided source
    bindings and unambiguous legacy displayed numbers are replaced in situ;
    declared {{tokens}} are substituted. User values are still reiterated as
    high-priority changes so the model retains the scene while changing only the
    requested objects/text. The full assembled prompt never reaches the client.
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
    bound_display_values: list[tuple[str, str]] = []
    for spec in specs:
        value = validated[spec.key]
        token_pattern = re.compile(r"\{\{\s*" + re.escape(spec.key) + r"\s*\}\}")
        rendered, token_count = token_pattern.subn(lambda _match, captured_value=value: captured_value, rendered)
        replacement = spec.original_value
        if not replacement and not token_count and _is_display_number_field(spec, value):
            replacement = _infer_display_number(base_prompt) or ""
        replaced = 0
        if replacement:
            rendered, replaced = _replace_literal(rendered, replacement, value)
            if spec.original_value and not replaced:
                raise TrendUserFieldsError(
                    f"Исходное значение поля «{spec.label}» не найдено в шаблоне"
                )
        if (token_count or replaced) and _is_display_number_field(spec, value):
            bound_display_values.append((spec.label, value))

    # The source scenario/camera/refs always remain the base; the instructions
    # below resolve any residual single-vs-multiple digits wording semantically.
    overrides = "\n".join(
        f"- {spec.label}: {validated[spec.key]}"
        for spec in specs
        if validated[spec.key]
    )
    if overrides:
        digit_rules = ""
        if bound_display_values:
            digit_rules = (
                "\nЦИФРЫ В КАДРЕ: показывайте только указанные пользователем "
                "числовые символы. Если введена одна цифра, нужна одна цифра "
                "(не две прежние свечи или два написанных знака); если цифр "
                "несколько, адаптируйте действия рисования и зажигания к новому "
                "количеству. Даже если на исходных фото/видео или торте видны "
                "старые числа, используйте их лишь как композиционный референс: "
                "в готовом результате нарисуйте или покажите только цифры пользователя. "
                "Старые числа из примера не выводить."
            )
        rendered = (
            f"{rendered}\n\n"
            "ВАЖНО: примените следующие параметры пользователя как приоритетные "
            "изменения. Если они противоречат исходному prompt, значения ниже имеют "
            "приоритет. Это НЕ новый сценарий: сохраните всю исходную сцену, "
            "героев, референсы, ракурсы, движение, свет и последовательность "
            f"действий. Меняйте только перечисленные детали:\n{overrides}{digit_rules}"
        )
    return rendered.strip()
