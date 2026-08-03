"""Apply user-facing copy fixes inside the production Docker image.

This build-time guard keeps production copy correct even while the large legacy
keyboard module is being split into smaller components. Every replacement is
strict: an unexpected source shape fails the image build instead of silently
shipping stale text.
"""

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one copy fragment in {path}, found {count}: {old!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "bot/keyboards.py",
        "from bot.services.preset_manager import preset_manager\n",
        "from bot.services.preset_manager import preset_manager\n"
        "from bot.services.photo_prompt_billing import photo_prompt_price_label\n",
    )
    replace_once(
        "bot/keyboards.py",
        'InlineKeyboardButton(text="✍️ Промпт по описанию", callback_data="photo_to_prompt"),',
        "InlineKeyboardButton(\n"
        '            text=f"✍️ Промпт по описанию • {photo_prompt_price_label()}",\n'
        '            callback_data="photo_to_prompt",\n'
        "        ),",
    )
    replace_once(
        "bot/handlers/image_analyzer.py",
        '        "📸 <b>Промпт по фото</b>\\n\\n"\n'
        '        f"Стоимость анализа фото: <b>{photo_prompt_price_label()}</b>\\n\\n"\n',
        '        "✍️ <b>Промпт по описанию</b>\\n\\n"\n'
        '        f"Стоимость: <b>{photo_prompt_price_label()}</b>\\n\\n"\n',
    )


if __name__ == "__main__":
    main()
