from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "bot" / "handlers" / "photo_prompt_vk_result_compat.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "photo_prompt_vk_result_compat_under_test",
        MODULE_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_photo_only_result_matches_vk_structure_exactly():
    module = _load_module()

    text, was_trimmed = module.format_vk_photo_prompt_result("Подробный промпт")

    assert was_trimmed is False
    assert text == (
        "✅ Готовый промпт:\n\n"
        "Подробный промпт\n\n"
        "Как использовать: скопируйте текст и вставьте его в экран «Создать фото» "
        "или «Создать видео». При необходимости добавьте свои правки: формат, "
        "настроение, цвет, действие."
    )


def test_long_photo_prompt_result_stays_inside_telegram_limit():
    module = _load_module()
    prompt = "детализированный промпт " * 500

    text, was_trimmed = module.format_vk_photo_prompt_result(prompt)

    assert was_trimmed is True
    assert len(text) <= module.TELEGRAM_MAX_MESSAGE_LENGTH
    assert text.startswith("✅ Готовый промпт:\n\n")
    assert "⚠️ Промпт был обрезан до лимита Telegram." in text


def test_handler_package_installs_vk_result_compat():
    source = (ROOT / "bot" / "handlers" / "__init__.py").read_text(encoding="utf-8")

    assert "install_vk_photo_prompt_result_compat" in source
    assert "install_vk_photo_prompt_result_compat()" in source


def test_voice_modes_keep_legacy_result_delivery():
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert 'result.get("source_mode")' in source
    assert '!= "photo"' in source
    assert "await original_send(" in source
