from bot.handlers.photo_prompt_vk_result_compat import format_prompt_readably


def test_short_prompt_is_not_rewritten():
    prompt = "Портрет девушки в мягком студийном свете."

    assert format_prompt_readably(prompt) == prompt


def test_long_prompt_is_split_into_readable_paragraphs():
    prompt = (
        "Девушка стоит у большого окна в светлой студии и смотрит прямо в камеру. "
        "На ней чёрное платье с матовой фактурой и тонкими серебряными деталями. "
        "Камера расположена на уровне глаз, средний портретный план, объектив 85 мм. "
        "Мягкий дневной свет идёт слева и создаёт аккуратный объём на лице. "
        "На заднем плане видны размытые растения, светлая стена и деревянный стол. "
        "Цветовая палитра нейтральная, с тёплыми бежевыми и холодными серыми оттенками. "
        "Сохранить естественную текстуру кожи, точные черты лица и реалистичные волосы. "
        "Фотореализм, высокая детализация, чистая композиция без лишних объектов."
    )

    formatted = format_prompt_readably(prompt)

    assert "\n\n" in formatted
    assert formatted.replace("\n\n", " ") == prompt


def test_existing_prompt_structure_is_preserved():
    prompt = "Персонаж:\nдевушка в красном пальто\n\nСвет:\nмягкий вечерний"

    assert format_prompt_readably(prompt) == prompt


def test_handler_package_keeps_compatibility_hook():
    with open("bot/handlers/__init__.py", encoding="utf-8") as source_file:
        source = source_file.read()

    assert "install_vk_photo_prompt_result_compat" in source
    assert "install_vk_photo_prompt_result_compat()" in source


def test_compatibility_layer_calls_legacy_detailed_sender():
    with open(
        "bot/handlers/photo_prompt_vk_result_compat.py",
        encoding="utf-8",
    ) as source_file:
        source = source_file.read()

    assert "await original_send(" in source
    assert "await message.answer(" not in source
    assert '== "photo"' in source


def test_legacy_result_still_contains_all_sections_and_document():
    with open("bot/handlers/image_analyzer.py", encoding="utf-8") as source_file:
        source = source_file.read()

    assert "<b>Prompt RU:</b>" in source
    assert "<b>Prompt EN:</b>" in source
    assert "<b>Negative prompt:</b>" in source
    assert "<b>Рекомендация:</b>" in source
    assert "await message.answer_document(" in source
