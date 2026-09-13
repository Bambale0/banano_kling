from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers import generation
from bot.keyboards import get_create_image_keyboard


def test_standard_image_keyboard_has_no_quantity_controls():
    keyboard = get_create_image_keyboard(current_count=6)
    callbacks = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    ]

    assert not any(value.startswith("img_count_") for value in callbacks)


def test_standard_image_screen_ignores_stale_batch_count(monkeypatch):
    monkeypatch.setattr(generation, "_resolve_image_unit_cost", lambda *_args: 3)

    text = generation._build_image_creation_text(
        {
            "img_service": "banana_pro",
            "img_ratio": "1:1",
            "img_count": 6,
            "reference_images": [],
            "img_quality": "2K",
        }
    )

    assert "Результат: <code>1 изображение</code>" in text
    assert "Стоимость: <code>3🍌</code>" in text
    assert "× 6" not in text


@pytest.mark.asyncio
async def test_legacy_quantity_button_resets_standard_generation_to_one(monkeypatch):
    callback = MagicMock()
    callback.data = "img_count_6"
    callback.answer = AsyncMock()
    state = MagicMock()
    state.update_data = AsyncMock()
    show_screen = AsyncMock()
    monkeypatch.setattr(generation, "_show_image_creation_screen", show_screen)

    await generation.handle_img_count(callback, state)

    state.update_data.assert_awaited_once_with(img_count=1)
    show_screen.assert_awaited_once_with(callback, state)
    callback.answer.assert_awaited_once_with("Обычная генерация создаёт 1 фото")


@pytest.mark.asyncio
async def test_stale_six_image_state_launches_only_one_standard_task(monkeypatch):
    message = MagicMock()
    message.text = "Фотореалистичный портрет девушки в студии"
    message.from_user.id = 123456
    processing = MagicMock()
    processing.edit_text = AsyncMock()
    processing.delete = AsyncMock()
    message.answer = AsyncMock(return_value=processing)

    state = MagicMock()
    state.get_data = AsyncMock(
        return_value={
            "generation_type": "image",
            "img_service": "banana_pro",
            "img_ratio": "1:1",
            "img_count": 6,
            "img_quality": "2K",
            "img_nsfw_checker": False,
            "reference_images": [],
            "nsfw_enabled": False,
        }
    )
    state.update_data = AsyncMock()
    state.clear = AsyncMock()

    monkeypatch.setattr(
        generation,
        "get_or_create_user",
        AsyncMock(return_value=SimpleNamespace(credits=100)),
    )
    monkeypatch.setattr(generation, "_resolve_image_unit_cost", lambda *_args: 2)
    monkeypatch.setattr(generation, "deduct_credits", AsyncMock(return_value=True))
    monkeypatch.setattr(generation, "_prompt_expects_reference_image", lambda _prompt: False)
    monkeypatch.setattr(
        generation,
        "_start_image_generation_task",
        AsyncMock(
            return_value={
                "status": "queued",
                "task_id": "provider-task-1",
                "local_task_id": "img_local_1",
            }
        ),
    )

    await generation.handle_image_prompt_text(message, state)

    generation.deduct_credits.assert_awaited_once_with(123456, 2)
    assert generation._start_image_generation_task.await_count == 1
    state.update_data.assert_any_await(img_count=1)
    state.clear.assert_awaited_once()


def test_mini_app_standard_image_generation_is_single_output():
    repo_root = Path(__file__).resolve().parents[1]
    form = (repo_root / "frontend/miniapp-v0/components/forms/image-generator-form.tsx").read_text()
    photo_tab = (repo_root / "frontend/miniapp-v0/components/tabs/photo-tab.tsx").read_text()

    assert "[1, 2, 4, 6]" not in form
    assert "selectedCount" not in form
    assert "count: number" not in form
    assert "for (let index = 0; index < data.count; index += 1)" not in photo_tab
    assert "count: number" not in photo_tab
