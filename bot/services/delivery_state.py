"""Delivery-state helpers shared by webhook and poller paths."""

from __future__ import annotations

import json

TASK_DELIVERY_STATUSES = frozenset(
    {
        "result_ready",
        "delivered",
        "failed",
        "pending",
        "link_sent",
        "unavailable",
    }
)
TERMINAL_TASK_DELIVERY_STATUSES = frozenset(
    {"delivered", "failed", "unavailable"}
)

_TERMINAL_TELEGRAM_DELIVERY_REASONS = (
    ("chat not found", "chat_not_found"),
    ("bot was blocked", "bot_blocked"),
    ("user is deactivated", "user_deactivated"),
)
TERMINAL_TELEGRAM_DELIVERY_ERRORS = tuple(
    fragment for fragment, _reason in _TERMINAL_TELEGRAM_DELIVERY_REASONS
)


def terminal_telegram_delivery_reason(error: Exception | str | None) -> str | None:
    """Return a stable reason when Telegram delivery needs user action to recover."""

    message = str(error or "").lower()
    for fragment, reason in _TERMINAL_TELEGRAM_DELIVERY_REASONS:
        if fragment in message:
            return reason
    return None


def is_terminal_telegram_delivery_error(error: Exception | str | None) -> bool:
    """Return True when retrying Telegram delivery cannot succeed without user action."""

    return terminal_telegram_delivery_reason(error) is not None


RETRYABLE_TASK_DELIVERY_STATUSES = frozenset(
    {"result_ready", "pending", "delivering", "link_sent"}
)


def has_retryable_result(task) -> bool:
    """Only explicitly tracked, completed results may be replayed for delivery."""
    try:
        metadata = json.loads(getattr(task, "request_data", None) or "{}")
    except (TypeError, ValueError):
        return False
    return bool(
        getattr(task, "status", None) == "completed"
        and getattr(task, "result_url", None)
        and isinstance(metadata, dict)
        and metadata.get("delivery_status") in RETRYABLE_TASK_DELIVERY_STATUSES
    )


def stored_result_payload(task) -> dict:
    """Rebuild success from our durable result, never from an untrusted callback."""
    url = str(task.result_url)
    data = {"taskId": task.task_id, "state": "success", "model": task.model or ""}
    if task.type in {"audio", "character"} and not url.startswith("http"):
        data["audioId" if task.type == "audio" else "characterId"] = url
    else:
        data["resultJson"] = json.dumps({"resultUrls": [url]})
        data["resultUrls"] = [url]  # Veo's normalized success shape.
    return {"code": 200, "data": data}


def retryable_result_sql(*, postgres: bool) -> str:
    """SQL selection for completed results that still need Telegram delivery."""
    state = (
        "request_data::jsonb ->> 'delivery_status'"
        if postgres else "json_extract(request_data, '$.delivery_status')"
    )
    return (
        "(status = 'completed' AND COALESCE(result_url, '') <> '' "
        "AND CASE WHEN json_valid(request_data) THEN " + state + " ELSE NULL END "
        "IN ('result_ready', 'pending', 'delivering', 'link_sent'))"
    )
