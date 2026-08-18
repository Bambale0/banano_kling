from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl


def is_trend_prompt(prompt: Mapping[str, Any] | None) -> bool:
    if not prompt:
        return False
    return any(
        str(tag or "").strip().lower() == "trend"
        for tag in list(prompt.get("tags") or [])
    )


def public_trend_settings(prompt: Mapping[str, Any]) -> dict[str, str]:
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

    return {"kind": kind, "ratio": ratio}


def sanitize_prompt_for_public(
    prompt: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Return public prompt metadata without a trend's executable recipe."""

    if prompt is None:
        return None

    payload = dict(prompt)
    if not is_trend_prompt(payload):
        return payload

    payload["prompt_text"] = ""
    payload["model"] = None
    payload["generation_settings"] = public_trend_settings(payload)
    payload["prompt_hidden"] = True
    payload["prompt_actions_allowed"] = False
    return payload


def sanitize_prompt_api_payload(payload: Any) -> Any:
    """Redact trend secrets in Mini App prompt list/detail mutation responses."""

    if not isinstance(payload, Mapping):
        return payload

    result = dict(payload)
    prompt = result.get("prompt")
    if isinstance(prompt, Mapping):
        result["prompt"] = sanitize_prompt_for_public(prompt)

    prompts = result.get("prompts")
    if isinstance(prompts, list):
        result["prompts"] = [
            sanitize_prompt_for_public(item) if isinstance(item, Mapping) else item
            for item in prompts
        ]

    return result


def telegram_id_from_init_data(init_data: Any) -> int | None:
    """Read the Telegram user id from already-validated Mini App initData."""

    try:
        fields = dict(parse_qsl(str(init_data or ""), keep_blank_values=True))
        raw_user = fields.get("user")
        if not raw_user:
            return None
        user = json.loads(raw_user)
        if not isinstance(user, Mapping):
            return None
        telegram_id = int(user.get("id") or 0)
        return telegram_id if telegram_id > 0 else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
