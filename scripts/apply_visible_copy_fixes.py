"""Validate and normalize user-facing copy for the production bot image.

The Telegram bot and Mini App are deployed in separate containers. This guard
only validates the text-bot image and fails the build if the expected source
layout changes.
"""


BUTTON_TEXT = (
    'InlineKeyboardButton(text="✍️ Промпт по описанию", '
    'callback_data="photo_to_prompt"),'
)
PRICE_IN_BUTTON_FRAGMENT = "Промпт по описанию •"

OLD_SCREEN = (
    '        "📸 <b>Промпт по фото</b>\\n\\n"\n'
    '        f"Стоимость анализа фото: <b>{photo_prompt_price_label()}</b>\\n\\n"\n'
)
NEW_SCREEN = (
    '        "✍️ <b>Промпт по описанию</b>\\n\\n"\n'
    '        f"Стоимость анализа: <b>{photo_prompt_price_label()}</b>\\n\\n"\n'
)


def read_text(path: str) -> str:
    with open(path, encoding="utf-8") as source:
        return source.read()


def write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as target:
        target.write(content)


def main() -> None:
    keyboard_path = "bot/keyboards.py"
    keyboard_text = read_text(keyboard_path)
    if BUTTON_TEXT not in keyboard_text:
        raise RuntimeError("Main-menu photo prompt button was not found")
    if PRICE_IN_BUTTON_FRAGMENT in keyboard_text:
        raise RuntimeError("Photo prompt price must not be shown in the menu button")

    handler_path = "bot/handlers/image_analyzer.py"
    handler_text = read_text(handler_path)
    if OLD_SCREEN in handler_text:
        handler_text = handler_text.replace(OLD_SCREEN, NEW_SCREEN, 1)
        write_text(handler_path, handler_text)
    elif NEW_SCREEN not in handler_text:
        raise RuntimeError("Photo prompt screen copy was not found")

    database_text = read_text("bot/database.py")
    if "PARTNER_NEW_USER_BONUS: int = 5" not in database_text:
        raise RuntimeError("New-user welcome bonus must be 5 bananas")


if __name__ == "__main__":
    main()
