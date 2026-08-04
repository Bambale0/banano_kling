"""Validate and normalize user-facing copy for the production image.

The Telegram bot and Mini App are shipped in the same Docker image. This guard
keeps the visible values aligned and fails the image build if the expected
source layout changes.
"""

from pathlib import Path


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


def main() -> None:
    keyboard_path = Path("bot/keyboards.py")
    keyboard_text = keyboard_path.read_text(encoding="utf-8")
    if BUTTON_TEXT not in keyboard_text:
        raise RuntimeError("Main-menu photo prompt button was not found")
    if PRICE_IN_BUTTON_FRAGMENT in keyboard_text:
        raise RuntimeError("Photo prompt price must not be shown in the menu button")

    handler_path = Path("bot/handlers/image_analyzer.py")
    handler_text = handler_path.read_text(encoding="utf-8")
    if OLD_SCREEN in handler_text:
        handler_text = handler_text.replace(OLD_SCREEN, NEW_SCREEN, 1)
        handler_path.write_text(handler_text, encoding="utf-8")
    elif NEW_SCREEN not in handler_text:
        raise RuntimeError("Photo prompt screen copy was not found")

    database_text = Path("bot/database.py").read_text(encoding="utf-8")
    if "PARTNER_NEW_USER_BONUS: int = 5" not in database_text:
        raise RuntimeError("New-user welcome bonus must be 5 bananas")

    balance_text = Path(
        "frontend/miniapp-v0/components/balance-sheet.tsx"
    ).read_text(encoding="utf-8")
    if "Welcome-бонус для новых пользователей: 5🍌" not in balance_text:
        raise RuntimeError("Mini App welcome bonus copy must show 5 bananas")
    if "Welcome-бонус для новых пользователей: 15🍌" in balance_text:
        raise RuntimeError("Stale 15-banana welcome bonus copy is still present")


if __name__ == "__main__":
    main()
