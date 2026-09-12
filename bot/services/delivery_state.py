"""Delivery-state helpers shared by webhook and poller paths."""

TERMINAL_TELEGRAM_DELIVERY_ERRORS = (
    "chat not found",
    "bot was blocked",
    "user is deactivated",
)


def is_terminal_telegram_delivery_error(error: Exception | str | None) -> bool:
    """Return True when retrying Telegram delivery cannot succeed without user action."""
    message = str(error or "").lower()
    return any(fragment in message for fragment in TERMINAL_TELEGRAM_DELIVERY_ERRORS)
