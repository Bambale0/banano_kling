from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl

from bot.trend_user_fields import TrendUserFieldsError, configured_user_fields


def is_trend_prompt(prompt: Mapping[str, Any] | None) -> bool:
    if not prompt:
        return False
    return any(
        str(tag or "").strip().lower() == "trend"
        for tag in list(prompt.get("tags") or [])
    )


def public_trend_settings(prompt: Mapping[str, Any]) -> dict[str, Any]:
    raw_settings = prompt.get("generation_settings")
    settings = raw_settings if isinstance(raw_settings, Mapping) else {}
    tags = {
        str(tag or "").strip().lower()
        for tag in list(prompt.get("tags") or [])
        if str(tag or "").strip()
    }

    kind = str(settings.get("kind") or "").strip().lower()
    if kind not in {"image", "video"}:
        kind = (
            "video"
            if str(prompt.get("category") or "").strip().lower() == "video"
            or "trend-video" in tags
            else "image"
        )

    ratio = str(settings.get("ratio") or "").strip()
    if not ratio:
        ratio = "16:9" if kind == "video" else "1:1"

    public_settings: dict[str, Any] = {"kind": kind, "ratio": ratio}
    # Public routing discriminator only: model and executable recipe stay private.
    if (
        kind == "video"
        and str(prompt.get("model") or "").strip() in {"wan_3", "wan_3_prime"}
        and type(settings.get("wan3_recipe_version")) is int
        and settings["wan3_recipe_version"] == 1
    ):
        public_settings["wan3_recipe_version"] = 1
    try:
        reference_count = int(settings.get("reference_count") or 0)
    except (TypeError, ValueError):
        reference_count = 0
    if 1 <= reference_count <= 12:
        public_settings["reference_count"] = reference_count
        raw_labels = settings.get("reference_labels")
        if isinstance(raw_labels, list):
            labels = [
                str(value or "").strip()[:80]
                for value in raw_labels[:reference_count]
                if str(value or "").strip()
            ]
            if labels:
                public_settings["reference_labels"] = labels
    if settings.get("automatic_hidden_references") is True:
        public_settings["automatic_hidden_references"] = True

    recipe_id = str(settings.get("genjutsu_recipe_id") or "").strip()
    if re.fullmatch(r"[a-f0-9]{32}", recipe_id):
        public_settings["genjutsu_recipe_id"] = recipe_id
    try:
        required_video_duration = int(
            settings.get("required_video_duration_seconds") or 0
        )
    except (TypeError, ValueError):
        required_video_duration = 0
    if 4 <= required_video_duration <= 30:
        public_settings["required_video_duration_seconds"] = required_video_duration
    raw_slots = settings.get("reference_slots")
    if isinstance(raw_slots, list) and 1 <= len(raw_slots) <= 12:
        slots: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        for raw_slot in raw_slots:
            if not isinstance(raw_slot, Mapping):
                slots = []
                break
            media_type = str(raw_slot.get("media_type") or "").strip().lower()
            label = str(raw_slot.get("label") or "").strip()[:80]
            try:
                position = int(raw_slot.get("position"))
            except (TypeError, ValueError):
                slots = []
                break
            key = (media_type, position)
            if (
                media_type not in {"image", "video", "audio"}
                or position < 1
                or not label
                or key in seen
            ):
                slots = []
                break
            seen.add(key)
            slots.append(
                {"media_type": media_type, "position": position, "label": label}
            )
        if len(slots) == reference_count:
            public_settings["reference_slots"] = slots

    try:
        user_fields = configured_user_fields(
            settings,
            prompt=str(prompt.get("prompt_text") or ""),
        )
    except TrendUserFieldsError:
        user_fields = []
    if user_fields:
        # A source anchor is a substring of the private author's recipe.
        # Return only user-facing labels and validation metadata to viewers.
        public_settings["user_fields"] = [
            {key: value for key, value in field.items() if key != "original_value"}
            for field in user_fields
        ]

    preview_type = str(settings.get("preview_type") or "").strip().lower()
    if preview_type in {"image", "video"}:
        public_settings["preview_type"] = preview_type
    return public_settings


def without_trend_repeat_statistics(prompt: Mapping[str, Any]) -> dict[str, Any]:
    """Copy viewer metadata without admin counters, including the legacy prefix."""
    payload = dict(prompt)
    if not is_trend_prompt(payload):
        return payload
    count = payload.pop("successful_runs_count", None)
    payload.pop("uses_count", None)
    # Only remove the exact system-generated prefix for this metric; never
    # rewrite an author's arbitrary description or mutate the shared DB result.
    if type(count) is int and count >= 0:
        prefix = f"✅ Успешных запусков: {count}"
        description = str(payload.get("description") or "").strip()
        if description == prefix:
            payload["description"] = ""
        elif description.startswith(prefix + " · "):
            payload["description"] = description[len(prefix + " · "):]
    return payload


def sanitize_prompt_for_public(
    prompt: Mapping[str, Any] | None,
    *,
    include_repeat_stats: bool = False,
) -> dict[str, Any] | None:
    """Return public prompt metadata without a trend's executable recipe."""

    if prompt is None:
        return None

    payload = dict(prompt)
    if not is_trend_prompt(payload):
        return payload

    if not include_repeat_stats:
        payload = without_trend_repeat_statistics(payload)
    public_settings = public_trend_settings(payload)
    # Legacy authors could publish without a description. create_prompt then
    # derives one from the SECRET recipe; redacting only prompt_text is not enough.
    private_text = " ".join(str(payload.get("prompt_text") or "").split())
    inferred = private_text[:197] + "..." if len(private_text) > 200 else private_text
    if private_text and str(payload.get("description") or "") == inferred:
        payload["description"] = ""
    payload["prompt_text"] = ""
    payload["model"] = None
    for internal_key in (
        "source_generation_id", "reject_reason",
        "ai_moderation_decision", "ai_moderation_risk",
        "ai_moderation_reason", "ai_moderation_recommendation",
        "ai_moderation_raw", "ai_moderated_at",
    ):
        payload.pop(internal_key, None)
    payload["generation_settings"] = public_settings
    payload["prompt_hidden"] = True
    payload["prompt_actions_allowed"] = False
    return payload


def sanitize_prompt_api_payload(
    payload: Any, *, include_repeat_stats: bool = False,
) -> Any:
    """Redact trend secrets in Mini App prompt list/detail mutation responses."""

    if not isinstance(payload, Mapping):
        return payload

    result = dict(payload)
    prompt = result.get("prompt")
    if isinstance(prompt, Mapping):
        result["prompt"] = sanitize_prompt_for_public(
            prompt, include_repeat_stats=include_repeat_stats,
        )

    prompts = result.get("prompts")
    if isinstance(prompts, list):
        result["prompts"] = [
            sanitize_prompt_for_public(item, include_repeat_stats=include_repeat_stats)
            if isinstance(item, Mapping) else item
            for item in prompts
        ]

    return result


def verified_telegram_id_from_init_data(init_data: Any, bot_token: str) -> int | None:
    """Return Telegram id only when Mini App initData has a valid bot signature."""

    try:
        parsed = dict(parse_qsl(str(init_data or ""), keep_blank_values=True))
        their_hash = str(parsed.pop("hash", "") or "")
        if not their_hash or not bot_token:
            return None

        data_check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(parsed.items())
        )
        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        expected_hash = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_hash, their_hash):
            return None

        raw_user = parsed.get("user")
        if not raw_user:
            return None
        user = json.loads(raw_user)
        if not isinstance(user, Mapping):
            return None
        telegram_id = int(user.get("id") or 0)
        return telegram_id if telegram_id > 0 else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
