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
ACTIVE_PROMPT_SCREEN = (
    '        "✨ <b>Анализ и создание промпта</b>\\n\\n"\n'
    '        f"Стоимость анализа: <b>{photo_prompt_price_label()}</b>\\n\\n"\n'
)
ACTIVE_PROMPT_SCREEN_WITHOUT_PRICE = (
    '        "✨ <b>Анализ и создание промпта</b>\\n\\n"\n'
    '        "Отправьте одним сообщением:\\n"\n'
)
ACTIVE_PROMPT_REPLACED_TITLE = "✍️ <b>Промпт по описанию</b>"

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
OLD_PARTNER_BONUS_COPY = (
    '        "• Каждый, кто перейдёт по вашей реферальной ссылке, получает '
    '🍌 <code>15</code> бананов для тестирования бота\\n"\n'
)
NEW_PARTNER_BONUS_COPY = (
    '        f"• Каждый, кто перейдёт по вашей реферальной ссылке, получает '
    '🍌 <code>{PARTNER_NEW_USER_BONUS}</code> бананов для тестирования бота\\n"\n'
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


def validate_active_prompt_analyzer_screen() -> None:
    handler_text = read_text("bot/handlers/prompt_analyzer_v2.py")
    if ACTIVE_PROMPT_SCREEN_WITHOUT_PRICE in handler_text:
        raise RuntimeError("Active prompt analyzer still misses the price line")
    if ACTIVE_PROMPT_SCREEN not in handler_text:
        raise RuntimeError("Active prompt analyzer price screen copy was not found")
    callback_block = handler_text.split('async def prompt_analyzer_handler', 1)[1].split(
        '@router.message', 1
    )[0]
    if ACTIVE_PROMPT_REPLACED_TITLE in callback_block:
        raise RuntimeError("Active prompt analyzer title must stay unchanged")
    for required_fragment in (
        "photo_prompt_price_label",
        "reserve_photo_prompt_charge",
        "refund_photo_prompt_charge",
        "PhotoPromptInsufficientBalance",
    ):
        if required_fragment not in handler_text:
            raise RuntimeError(
                f"Active prompt analyzer is missing billing fragment: {required_fragment}"
            )


def normalize_runtime_bonus_copy() -> None:
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

    if OLD_PARTNER_BONUS_COPY in handler_text:
        handler_text = handler_text.replace(
            OLD_PARTNER_BONUS_COPY,
            NEW_PARTNER_BONUS_COPY,
            1,
        )
    elif NEW_PARTNER_BONUS_COPY not in handler_text:
        raise RuntimeError("Telegram partner cabinet bonus copy was not found")

    stale_fragments = (
        "Новым пользователям — 15 бананов",
        "<code>15</code> бананов для тестирования бота",
    )
    for fragment in stale_fragments:
        if fragment in handler_text:
            raise RuntimeError(f"Stale Telegram bonus copy remains: {fragment}")

    write_text(handler_path, handler_text)


def main() -> None:
    keyboard_path = "bot/keyboards.py"
    keyboard_text = read_text(keyboard_path)
    if BUTTON_TEXT not in keyboard_text:
        raise RuntimeError("Main-menu photo prompt button was not found")
    if PRICE_IN_BUTTON_FRAGMENT in keyboard_text:
        raise RuntimeError("Photo prompt price must not be shown in the menu button")

    normalize_photo_prompt_screen()
    validate_active_prompt_analyzer_screen()
    normalize_runtime_bonus_copy()

    database_text = read_text("bot/database.py")
    if "PARTNER_NEW_USER_BONUS: int = 5" not in database_text:
        raise RuntimeError("New-user welcome bonus must be 5 bananas")


if __name__ == "__main__":
    main()
