from bot.keyboards import get_image_result_keyboard


def test_completed_image_result_keeps_repeat_action() -> None:
    keyboard = get_image_result_keyboard(
        "https://example.com/generated.png",
        task_id="image-42",
    )
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.text == "🔁 Повторить" for button in buttons)
    assert any(
        button.callback_data in {"repeat_image_image-42", "repeat_result_image-42"}
        for button in buttons
    )
