from bot.services.delivery_state import is_terminal_telegram_delivery_error


def test_terminal_telegram_delivery_errors_are_not_retried_forever():
    assert is_terminal_telegram_delivery_error("Bad Request: chat not found")
    assert is_terminal_telegram_delivery_error("Forbidden: bot was blocked by the user")
    assert is_terminal_telegram_delivery_error("Bad Request: user is deactivated")


def test_transient_telegram_delivery_errors_remain_recoverable():
    assert not is_terminal_telegram_delivery_error(TimeoutError("request timeout"))
    assert not is_terminal_telegram_delivery_error("Too Many Requests: retry after 3")
    assert not is_terminal_telegram_delivery_error("network error")


def test_terminal_telegram_delivery_reason_is_structured():
    from bot.services.delivery_state import terminal_telegram_delivery_reason

    assert (
        terminal_telegram_delivery_reason("Bad Request: chat not found")
        == "chat_not_found"
    )
    assert (
        terminal_telegram_delivery_reason("Forbidden: bot was blocked by the user")
        == "bot_blocked"
    )
    assert (
        terminal_telegram_delivery_reason("Bad Request: user is deactivated")
        == "user_deactivated"
    )
    assert terminal_telegram_delivery_reason("network error") is None
