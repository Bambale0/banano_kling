"""Admin-preview personalization for repeats of ordinary publications.

The browser only receives labels and validation metadata. Source bindings and the
assembled prompt stay behind the authenticated server boundary.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from bot import db as db_backend
from bot.trend_user_fields import (
    configured_user_fields,
    normalize_user_fields_settings,
    render_trend_prompt,
)

FEATURE_FLAG = "REPEAT_PERSONALIZATION_ADMIN_PREVIEW_ENABLED"
MAX_CHOICES = 12
MAX_CHOICE_LENGTH = 80

def admin_preview_enabled() -> bool:
    return str(os.getenv(FEATURE_FLAG, "")).strip().lower() in {
        "1", "true", "yes", "on",
    }


def normalize_repeat_fields(raw_fields: Any, *, prompt: str) -> list[dict[str, Any]]:
    if raw_fields == []:
        return []
    settings = normalize_user_fields_settings(
        {"user_fields": raw_fields},
        prompt=str(prompt or ""),
    )
    fields = configured_user_fields(settings, prompt=str(prompt or ""))
    raw_by_key = {
        str(field.get("key") or field.get("label") or "").strip(): field
        for field in raw_fields or []
        if isinstance(field, Mapping)
    }
    for field in fields:
        raw_choices = raw_by_key.get(str(field["key"]), {}).get("choices", [])
        if raw_choices in (None, ""):
            raw_choices = []
        if not isinstance(raw_choices, list) or len(raw_choices) > MAX_CHOICES:
            raise ValueError(f"Для поля «{field['label']}» можно задать не больше {MAX_CHOICES} вариантов")
        choices = [str(value or "").strip() for value in raw_choices]
        if any(not value or len(value) > MAX_CHOICE_LENGTH for value in choices):
            raise ValueError(f"Варианты поля «{field['label']}» настроены неверно")
        if len({value.casefold() for value in choices}) != len(choices):
            raise ValueError(f"Варианты поля «{field['label']}» не должны повторяться")
        if choices:
            # The author must not publish a button that the repeat validator
            # will reject (e.g. a number field containing "18 лет").
            for choice in choices:
                render_trend_prompt(
                    str(prompt or ""), {"user_fields": [field]}, {field["key"]: choice},
                )
            field["choices"] = choices
    if any(not str(field.get("original_value") or "").strip() for field in fields):
        raise ValueError("Для каждого параметра укажите точный исходный фрагмент промпта")
    spans: list[list[tuple[int, int]]] = []
    for field in fields:
        binding = str(field["original_value"]).strip()
        pattern = (
            re.compile(r"(?<![\w:.])" + re.escape(binding) + r"(?![\w:]|\.\d)", re.IGNORECASE)
            if binding.isdigit()
            else re.compile(r"(?<!\w)" + re.escape(binding) + r"(?!\w)", re.IGNORECASE)
        )
        spans.append([match.span() for match in pattern.finditer(str(prompt or ""))])
    for index, matches in enumerate(spans):
        for other_index in range(index + 1, len(spans)):
            if any(
                left_start < right_end and right_start < left_end
                for left_start, left_end in matches
                for right_start, right_end in spans[other_index]
            ):
                raise ValueError("Исходные фрагменты параметров не должны совпадать или пересекаться")
    return fields


def public_repeat_fields(fields: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in dict(field).items() if key != "original_value"}
        for field in fields
    ]


def render_repeat_base(
    source_prompt: str,
    fields: Sequence[Mapping[str, Any]],
    raw_values: Any,
) -> str:
    values = raw_values if isinstance(raw_values, Mapping) else {}
    for field in fields:
        choices = list(field.get("choices") or [])
        value = str(values.get(str(field.get("key") or ""), "") or "").strip()
        if choices and value not in choices:
            raise ValueError(f"Выберите один из вариантов поля «{field.get('label') or field.get('key')}»")
    unknown = set(values) - {str(field["key"]) for field in fields}
    if unknown:
        raise ValueError("Переданы лишние поля повтора")
    # Hide all source spans behind fresh private bindings before rendering.
    # Neither another original fragment nor a {{field}} in an inserted value
    # can be interpreted again by a later field's substitution.
    replacements = []
    private_fields = []
    private_values = {}
    source = str(source_prompt or "")
    for field in fields:
        binding = str(field.get("original_value") or "").strip()
        pattern = (
            re.compile(r"(?<![\w:.])" + re.escape(binding) + r"(?![\w:]|\.\d)", re.IGNORECASE)
            if binding.isdigit()
            else re.compile(r"(?<!\w)" + re.escape(binding) + r"(?!\w)", re.IGNORECASE)
        )
        matches = list(pattern.finditer(source)) if binding else []
        if not matches:
            raise ValueError(f"Исходное значение поля «{field['label']}» не найдено в шаблоне")
        token = "rp" + uuid.uuid4().hex
        private_fields.append({**dict(field), "key": token, "original_value": token})
        private_values[token] = values.get(str(field["key"]), "")
        replacements.extend((match.start(), match.end(), token) for match in matches)
    masked = source
    previous_start = len(source) + 1
    for start, end, token in sorted(replacements, reverse=True):
        if end > previous_start:
            raise ValueError("Исходные фрагменты параметров не должны пересекаться")
        masked = masked[:start] + token + masked[end:]
        previous_start = start
    return render_trend_prompt(masked, {"user_fields": private_fields}, private_values)


async def save_repeat_fields(
    generation_id: int,
    fields: Sequence[Mapping[str, Any]],
    *,
    actor_telegram_id: int,
) -> tuple[str, list[dict[str, Any]]]:
    return await _replace_repeat_fields(
        generation_id,
        fields,
        actor_telegram_id=actor_telegram_id,
    )


async def clear_repeat_fields(
    generation_id: int,
    *,
    actor_telegram_id: int,
) -> tuple[str, list[dict[str, Any]]]:
    """Store a revisioned empty value so a failed stale request cannot resurrect data."""

    return await _replace_repeat_fields(
        generation_id,
        [],
        actor_telegram_id=actor_telegram_id,
    )


async def _replace_repeat_fields(
    generation_id: int,
    fields: Sequence[Mapping[str, Any]],
    *,
    actor_telegram_id: int,
) -> tuple[str, list[dict[str, Any]]]:
    payload = json.dumps(
        [dict(field) for field in fields],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    write_token = uuid.uuid4().hex
    async with db_backend.connect() as db:
        await db.execute("BEGIN" if db_backend.is_postgres() else "BEGIN IMMEDIATE")
        if db_backend.is_postgres():
            # PostgreSQL's plain BEGIN does not serialize the read below. Lock
            # the stable parent row so same-generation updates observe the
            # immediately preceding committed personalization revision.
            await db.execute(
                "SELECT id FROM generation_tasks WHERE id = ? FOR UPDATE",
                (int(generation_id),),
            )
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            "SELECT fields_json FROM generation_repeat_personalization WHERE generation_id = ?",
            (int(generation_id),),
        )
        row = await cursor.fetchone()
        previous_fields = _decode_fields(row["fields_json"]) if row else []
        await db.execute(
            """
            INSERT INTO generation_repeat_personalization (
                generation_id, fields_json, write_token, updated_by_telegram_id, updated_at
            ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(generation_id) DO UPDATE SET
                fields_json = excluded.fields_json,
                write_token = excluded.write_token,
                updated_by_telegram_id = excluded.updated_by_telegram_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (int(generation_id), payload, write_token, int(actor_telegram_id)),
        )
        await db.commit()
    return write_token, previous_fields


async def restore_repeat_fields_if_current(
    generation_id: int,
    *,
    expected_token: str,
    previous_fields: Sequence[Mapping[str, Any]],
    actor_telegram_id: int,
) -> bool:
    """Compensate one failed publish without overwriting a newer concurrent edit."""

    previous = json.dumps([dict(field) for field in previous_fields], ensure_ascii=False, separators=(",", ":"))
    async with db_backend.connect() as db:
        if previous_fields:
            restore_token = uuid.uuid4().hex
            cursor = await db.execute(
                """
                UPDATE generation_repeat_personalization
                SET fields_json = ?, write_token = ?, updated_by_telegram_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE generation_id = ? AND write_token = ?
                """,
                (
                    previous,
                    restore_token,
                    int(actor_telegram_id),
                    int(generation_id),
                    str(expected_token),
                ),
            )
        else:
            cursor = await db.execute(
                "DELETE FROM generation_repeat_personalization WHERE generation_id = ? AND write_token = ?",
                (int(generation_id), str(expected_token)),
            )
        await db.commit()
        return bool(cursor.rowcount)


def _decode_fields(raw: Any) -> list[dict[str, Any]]:
    try:
        value = json.loads(str(raw or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(value, list):
        return []
    try:
        fields = configured_user_fields({"user_fields": value})
        choices_by_key = {
            str(field.get("key") or ""): list(field.get("choices") or [])
            for field in value
            if isinstance(field, Mapping)
        }
        for field in fields:
            choices = choices_by_key.get(str(field["key"]), [])
            if choices:
                field["choices"] = choices
        return fields
    except ValueError:
        return []


async def get_repeat_fields(generation_id: int) -> list[dict[str, Any]]:
    values = await get_repeat_fields_many([generation_id])
    return values.get(int(generation_id), [])


async def get_repeat_fields_many(
    generation_ids: Sequence[int],
) -> dict[int, list[dict[str, Any]]]:
    ids = list(dict.fromkeys(int(value) for value in generation_ids if int(value) > 0))
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            "SELECT generation_id, fields_json FROM generation_repeat_personalization "
            f"WHERE generation_id IN ({placeholders})",
            tuple(ids),
        )
        rows = await cursor.fetchall()
    result: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        fields = _decode_fields(row["fields_json"])
        if fields:
            result[int(row["generation_id"])] = fields
    return result
