"""Verified generation destination metadata shared by Mini App pipelines."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_ACCOUNT_ID = re.compile(r"[0-9a-f]{32}")


def generation_origin_metadata(
    *,
    origin_platform: str = "telegram",
    origin_vk_user_id: int | None = None,
    origin_account_id: str | None = None,
    vk_chat_delivery_requested: bool = False,
) -> dict[str, Any]:
    """Validate one server-resolved origin and return its durable task snapshot."""
    platform = str(origin_platform or "telegram").strip().lower()
    if platform == "telegram":
        return {"origin_platform": "telegram"}
    if platform != "vk":
        raise ValueError("invalid_origin_platform")
    if type(origin_vk_user_id) is not int or origin_vk_user_id <= 0:
        raise ValueError("invalid_vk_recipient")
    if not isinstance(origin_account_id, str) or not _ACCOUNT_ID.fullmatch(origin_account_id):
        raise ValueError("invalid_vk_account")
    return {
        "origin_platform": "vk",
        "origin_vk_user_id": origin_vk_user_id,
        "origin_account_id": origin_account_id,
        "vk_chat_delivery_requested": vk_chat_delivery_requested is True,
    }


def generation_origin_from_context(context: Mapping[str, Any] | None) -> dict[str, Any]:
    """Use only authenticated server context; never trust origin fields from JSON."""
    context = context or {}
    platform = str(context.get("platform") or "telegram").strip().lower()
    return generation_origin_metadata(
        origin_platform=platform,
        origin_vk_user_id=(
            context.get("platform_external_id") if platform == "vk" else None
        ),
        origin_account_id=(
            context.get("shared_account_id") if platform == "vk" else None
        ),
        vk_chat_delivery_requested=(
            context.get("vk_chat_delivery_requested") is True
        ),
    )
