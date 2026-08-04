"""Validate and normalize user-facing copy for the production bot image.

The Telegram bot and Mini App are deployed separately. This guard validates
and normalizes only the text-bot image and fails the build if the expected
source layout changes.
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

DATABASE_IMPORT_ANCHOR = "    PARTNER_INVITER_BONUS,\n"
DATABASE_IMPORT_WITH_WELCOME_BONUS = (
    "    PARTNER_INVITER_BONUS,\n"
    "    PARTNER_NEW_USER_BONUS,\n"
)
OLD_WELCOME_COPY = (
    '        "🎁 <b>Новым пользователям — 15 бананов в подарок!</b>\\n"\n'
)
NEW_WELCOME_COPY = (
    '        f"🎁 <b>Новым пользователям — {PARTNER_NEW_USER_BONUS} '
    'бананов в подарок!</b>\\n"\n'
)


def read_text(path: str) -> str:
    with open(path, encoding="utf-8") as source:
        return source.read()


def write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as target:
        target.write(content)


def normalize_photo_prompt_screen() -> None:
    handler_path = "bot/handlers/image_analyzer.py"
    handler_text = read_text(handler_path)
    if OLD_SCREEN in handler_text:
        handler_text = handler_text.replace(OLD_SCREEN, NEW_SCREEN, 1)
        write_text(handler_path, handler_text)
    elif NEW_SCREEN not in handler_text:
        raise RuntimeError("Photo prompt screen copy was not found")


def normalize_welcome_bonus_copy() -> None:
    handler_path = "bot/handlers/common.py"
    handler_text = read_text(handler_path)

    if "    PARTNER_NEW_USER_BONUS,\n" not in handler_text:
        if DATABASE_IMPORT_ANCHOR not in handler_text:
            raise RuntimeError("Welcome bonus database import anchor was not found")
        handler_text = handler_text.replace(
            DATABASE_IMPORT_ANCHOR,
            DATABASE_IMPORT_WITH_WELCOME_BONUS,
            1,
        )

    if OLD_WELCOME_COPY in handler_text:
        handler_text = handler_text.replace(
            OLD_WELCOME_COPY,
            NEW_WELCOME_COPY,
            1,
        )
    elif NEW_WELCOME_COPY not in handler_text:
        raise RuntimeError("Telegram welcome bonus copy was not found")

    if "Новым пользователям — 15 бананов" in handler_text:
        raise RuntimeError("Stale 15-banana Telegram welcome copy remains")

    write_text(handler_path, handler_text)


def main() -> None:
    keyboard_path = "bot/keyboards.py"
    keyboard_text = read_text(keyboard_path)
    if BUTTON_TEXT not in keyboard_text:
        raise RuntimeError("Main-menu photo prompt button was not found")
    if PRICE_IN_BUTTON_FRAGMENT in keyboard_text:
        raise RuntimeError("Photo prompt price must not be shown in the menu button")

    normalize_photo_prompt_screen()
    normalize_welcome_bonus_copy()

    database_text = read_text("bot/database.py")
    if "PARTNER_NEW_USER_BONUS: int = 5" not in database_text:
        raise RuntimeError("New-user welcome bonus must be 5 bananas")


if __name__ == "__main__":
    main()
