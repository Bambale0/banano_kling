"""Delivery-state helpers shared by webhook and poller paths."""

from __future__ import annotations

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
