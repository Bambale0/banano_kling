from bot.handlers.photo_prompt_vk_result_compat import (
    TELEGRAM_MAX_MESSAGE_LENGTH,
    format_vk_photo_prompt_result,
)


def test_photo_only_result_matches_vk_structure_exactly():
    text, was_trimmed = format_vk_photo_prompt_result("Подробный промпт")

    assert was_trimmed is False
    assert text == (
        "✅ Готовый промпт:\n\n"
        "Подробный промпт\n\n"
        "Как использовать: скопируйте текст и вставьте его в экран «Создать фото» "
        "или «Создать видео». При необходимости добавьте свои правки: формат, "
        "настроение, цвет, действие."
    )


def test_long_photo_prompt_result_stays_inside_telegram_limit():
    prompt = "детализированный промпт " * 500

    text, was_trimmed = format_vk_photo_prompt_result(prompt)

    assert was_trimmed is True
    assert len(text) <= TELEGRAM_MAX_MESSAGE_LENGTH
    assert text.startswith("✅ Готовый промпт:\n\n")
    assert "⚠️ Промпт был обрезан до лимита Telegram." in text


def test_handler_package_installs_vk_result_compat():
    with open("bot/handlers/__init__.py", encoding="utf-8") as source_file:
        source = source_file.read()

    assert "install_vk_photo_prompt_result_compat" in source
    assert "install_vk_photo_prompt_result_compat()" in source


def test_voice_modes_keep_legacy_result_delivery():
    with open(
        "bot/handlers/photo_prompt_vk_result_compat.py",
        encoding="utf-8",
    ) as source_file:
        source = source_file.read()

    assert 'result.get("source_mode")' in source
    assert '!= "photo"' in source
    assert "await original_send(" in source
