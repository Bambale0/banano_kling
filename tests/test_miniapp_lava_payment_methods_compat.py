from bot.handlers.miniapp_lava_payment_methods_compat import _payment_error_message


def test_payment_error_message_extracts_nested_lava_error() -> None:
    assert (
        _payment_error_message(
            {
                "ok": False,
                "error": {
                    "message": "Lava rejected payment creation",
                },
            }
        )
        == "Lava rejected payment creation"
    )


def test_payment_error_message_falls_back_to_plain_text() -> None:
    assert _payment_error_message(None) == "Failed to create payment"
